"""Create one new synthetic tenant and upload observations on every run.

Place in project root, start Docker Compose, then: python3 populate_demo_data.py
Only targets the local development database patient_monitoring.
"""
import asyncio
import json
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ================== EDIT THESE VALUES ==================
TENANT_NAME = "Generated Demo Hospital"
PATIENTS = 10
CLINICIANS = 3
DEVICES_PER_PATIENT = 1
CARE_TEAM = "round_robin"  # "round_robin" or "all" (each clinician assigned every patient)
OBSERVATIONS_PER_DEVICE = 100
BATCH_SIZE = 50
CONCURRENCY = 10
DUPLICATE_RETRY_PERCENTAGE = 10  # 0 disables retries; 100 retries every batch
API_URL = "http://127.0.0.1:8000"
# =======================================================

# This code runs inside the existing API container. It creates identities and
# memberships transactionally; observations are NOT inserted directly into DB.
PROVISION_CODE = r'''
import json, os, sys, uuid
from sqlalchemy.engine import make_url
from scripts.run_container_api import docker_database_url
url = make_url(os.environ['DATABASE_URL'])
if url.database != 'patient_monitoring':
    raise SystemExit('Refusing to seed anything other than patient_monitoring')
os.environ['DATABASE_URL'] = docker_database_url('DATABASE_URL')
from app.database import SessionLocal
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.device import Device
from app.models.staff import StaffUser, CareTeamMembership
from app.services.device_auth import generate_device_token, hash_device_token
from app.services.staff_auth import new_staff_token, hash_staff_token

cfg = json.loads(sys.stdin.readline())
run_id = uuid.uuid4().hex[:10]
output = {'tenant_id': None, 'patients': [], 'clinicians': [], 'devices': [], 'memberships': 0}
with SessionLocal.begin() as db:
    tenant_id = uuid.uuid4()
    db.add(Tenant(id=tenant_id, name=f"{cfg['tenant_name']} ({run_id})"))
    db.flush()
    output['tenant_id'] = str(tenant_id)
    for i in range(cfg['clinicians']):
        staff_id = uuid.uuid4()
        token = new_staff_token()
        db.add(StaffUser(id=staff_id, tenant_id=tenant_id, role='clinician', token_hash=hash_staff_token(token)))
        output['clinicians'].append({'staff_id': str(staff_id), 'token': token})
    db.flush()
    for i in range(cfg['patients']):
        patient_id = uuid.uuid4()
        external_id = f"GEN-{run_id}-{i+1:05d}"
        db.add(Patient(id=patient_id, tenant_id=tenant_id, external_id=external_id,
                       timezone='UTC', consent_active=True))
        output['patients'].append({'patient_id': str(patient_id), 'external_id': external_id})
        db.flush()
        for j in range(cfg['devices_per_patient']):
            device_id = uuid.uuid4()
            token = generate_device_token()
            db.add(Device(id=device_id, tenant_id=tenant_id, patient_id=patient_id,
                          token_hash=hash_device_token(token)))
            output['devices'].append({'device_id': str(device_id), 'patient_id': str(patient_id), 'token': token})
        selected = (range(cfg['clinicians']) if cfg['care_team'] == 'all'
                    else [i % cfg['clinicians']])
        for clinician_index in selected:
            db.add(CareTeamMembership(id=uuid.uuid4(), tenant_id=tenant_id,
                staff_id=uuid.UUID(output['clinicians'][clinician_index]['staff_id']), patient_id=patient_id))
            output['memberships'] += 1
print(json.dumps(output))
'''


def validate():
    if any(not isinstance(x, int) or isinstance(x, bool) or x < 1 for x in
           (PATIENTS, CLINICIANS, DEVICES_PER_PATIENT, OBSERVATIONS_PER_DEVICE, BATCH_SIZE, CONCURRENCY)):
        sys.exit('All numeric settings must be positive integers.')
    if not isinstance(DUPLICATE_RETRY_PERCENTAGE, int) or isinstance(DUPLICATE_RETRY_PERCENTAGE, bool) or not 0 <= DUPLICATE_RETRY_PERCENTAGE <= 100:
        sys.exit('DUPLICATE_RETRY_PERCENTAGE must be an integer between 0 and 100.')
    if CARE_TEAM not in ('round_robin', 'all'):
        sys.exit("CARE_TEAM must be 'round_robin' or 'all'.")
    if API_URL.rstrip('/') not in ('http://127.0.0.1:8000', 'http://localhost:8000'):
        sys.exit('Safety check: only the local development API on port 8000 is allowed.')


def provision():
    config = dict(tenant_name=TENANT_NAME, patients=PATIENTS, clinicians=CLINICIANS,
                  devices_per_patient=DEVICES_PER_PATIENT, care_team=CARE_TEAM)
    command = ['docker', 'compose', 'exec', '-T', 'api', 'python', '-c',
               'import sys; exec(sys.stdin.readline()); exec(sys.stdin.read())']
    # First line is a harmless Python statement; the remainder is executable source.
    stdin = 'pass\n' + "import io, sys\nsys.stdin = io.StringIO(" + repr(json.dumps(config) + '\n') + ")\n" + PROVISION_CODE
    result = subprocess.run(command, input=stdin, text=True, capture_output=True)
    if result.returncode:
        sys.exit('Provisioning failed:\n' + result.stderr + '\n' + result.stdout)
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        sys.exit('Could not read provisioning result:\n' + result.stdout)


def observation(device_id, index, now):
    # Rotate through realistic valid readings, including occasional low SpO2.
    metrics = [
        ('heart_rate', 72 + (index % 25), '/min'),
        ('spo2', 90 if index % 31 == 0 else 98, '%'),
        ('body_temp', 37.1, 'Cel'),
        ('symptom_score', 2, None),
    ]
    metric, value, unit = metrics[index % len(metrics)]
    item = {'client_obs_id': f'generated-{uuid.uuid4().hex}', 'type': metric,
            'value': value, 'effective_at': (now - timedelta(minutes=index)).isoformat()}
    if unit is not None:
        item['unit'] = unit
    return item


async def upload(devices):
    import httpx
    semaphore = asyncio.Semaphore(CONCURRENCY)
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        request_log = []

        async def send(device, start, retry_duplicate):
            items = [observation(device['device_id'], i, now)
                     for i in range(start, min(start + BATCH_SIZE, OBSERVATIONS_PER_DEVICE))]
            key = 'generated-' + uuid.uuid4().hex
            payload = {'batch_id': key, 'sent_at_device': now.isoformat(), 'observations': items}
            headers = {'Authorization': 'Bearer ' + device['token'], 'Idempotency-Key': key}
            url = f"{API_URL}/v1/devices/{device['device_id']}/observations:batch"
            async with semaphore:
                try:
                    original_log_index = len(request_log)
                    request_log.append(('original', len(items), 'attempted'))
                    response = await client.post(url, json=payload, headers=headers)
                    request_log[original_log_index] = ('original', len(items), response.status_code)
                    if response.status_code != 200:
                        return 0, len(items), 0, f'HTTP {response.status_code}: {response.text[:250]}'
                    results = response.json().get('results', [])
                    accepted = sum(item.get('status') == 'accepted' for item in results)
                    error = None if accepted == len(items) else str(results[:3])
                    retried = 0
                    if retry_duplicate and error is None:
                        # Simulate a lost response: resend the EXACT same batch,
                        # including client observation IDs, batch ID and idempotency key.
                        # Do not count replayed observations as new inserts.
                        replay_log_index = len(request_log)
                        request_log.append(('duplicate', len(items), 'attempted'))
                        replay = await client.post(url, json=payload, headers=headers)
                        request_log[replay_log_index] = ('duplicate', len(items), replay.status_code)
                        retried = len(items)
                        if replay.status_code != 200:
                            error = f'Duplicate replay HTTP {replay.status_code}: {replay.text[:250]}'
                    return accepted, len(items) - accepted, retried, error
                except httpx.RequestError as exc:
                    return 0, len(items), 0, str(exc)
        batches = [(device, start) for device in devices
                   for start in range(0, OBSERVATIONS_PER_DEVICE, BATCH_SIZE)]
        tasks = [send(device, start, (index * DUPLICATE_RETRY_PERCENTAGE) // 100 !=
                      ((index + 1) * DUPLICATE_RETRY_PERCENTAGE) // 100)
                 for index, (device, start) in enumerate(batches)]
        results = await asyncio.gather(*tasks)
    return (sum(x[0] for x in results), sum(x[1] for x in results),
            sum(x[2] for x in results), [x[3] for x in results if x[3]], request_log)


def main():
    validate()
    try:
        import httpx  # noqa: F401
    except ImportError:
        sys.exit('Missing httpx. Install project requirements in your local Python environment.')
    print(f'Creating one tenant, {PATIENTS} patients, {CLINICIANS} clinicians, '
          f'{PATIENTS * DEVICES_PER_PATIENT} devices and '
          f'{PATIENTS if CARE_TEAM == "round_robin" else PATIENTS * CLINICIANS} memberships...', flush=True)
    credentials = provision()
    # Keep the credentials private; never commit them. New filename per run.
    path = Path(__file__).resolve().parent / f"generated-credentials-{credentials['tenant_id']}.json"
    path.write_text(json.dumps(credentials, indent=2), encoding='utf-8')
    try:
        path.chmod(0o600)
    except OSError:
        pass
    print(f"Created tenant {credentials['tenant_id']}")
    print(f"Credentials saved to {path.name} (PRIVATE: do not commit)")
    expected = len(credentials['devices']) * OBSERVATIONS_PER_DEVICE
    print(f'Uploading {expected:,} observations through the API...', flush=True)
    accepted, rejected, replayed, errors, request_log = asyncio.run(upload(credentials['devices']))
    print(f'Accepted (new): {accepted:,}; not accepted: {rejected:,}')
    print(f'Duplicate observations replayed: {replayed:,} (not counted as new)')
    original_requests = [entry for entry in request_log if entry[0] == 'original']
    duplicate_requests = [entry for entry in request_log if entry[0] == 'duplicate']
    successful = [entry for entry in request_log if entry[2] == 200]
    print('\nHTTP request summary (recorded at each client.post call):')
    print(f'  Original HTTP requests attempted: {len(original_requests):,}')
    print(f'  Duplicate HTTP requests attempted: {len(duplicate_requests):,}')
    print(f'  Total HTTP requests attempted: {len(request_log):,}')
    print(f'  HTTP 200 responses received: {len(successful):,}')
    print(f'  Observation entries attempted: {sum(entry[1] for entry in request_log):,}')
    print(f'  Observation entries with HTTP 200: {sum(entry[1] for entry in successful):,}')
    other_statuses = [entry[2] for entry in request_log if entry[2] != 200]
    if other_statuses:
        print(f'  Non-200 / no-response attempts: {other_statuses}')
    for error in errors[:5]:
        print('  Error:', error)
    if rejected or errors:
        sys.exit('Some requests failed. Tenant and credentials were still created.')
    print('Complete. All records were sent to the development application.')


if __name__ == '__main__':
    main()

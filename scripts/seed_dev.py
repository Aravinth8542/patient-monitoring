"""Idempotent synthetic development seed. Run: python -m scripts.seed_dev"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import SessionLocal
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.device import Device
from app.models.observation import Observation
from app.services.device_auth import generate_device_token, hash_device_token

NAMESPACE = uuid.UUID('ab632718-1849-4a4c-910e-73272baf94f1')

def stable_id(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f'{kind}:{key}')

def assert_dev_database():
    url = make_url(settings.database_url)
    db_name = (url.database or '').lower()
    if db_name != 'patient_monitoring':
        raise SystemExit(f'Refusing to seed database {db_name!r}; expected exactly patient_monitoring.')
    if url.get_backend_name() != 'postgresql':
        raise SystemExit('This seed script requires PostgreSQL.')


def main():
    assert_dev_database()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    issued_tokens = []
    created = {'tenants': 0, 'patients': 0, 'devices': 0, 'observations': 0}
    hospitals = [
        ('north', 'North Demo Hospital', [
            ('NORTH-001', 'Asia/Kolkata', True),
            ('NORTH-002', 'Asia/Kolkata', True),
        ]),
        ('south', 'South Demo Clinic', [
            ('SOUTH-001', 'Asia/Kolkata', True),
            ('SOUTH-002', 'Asia/Kolkata', True),
        ]),
    ]
    with SessionLocal.begin() as db:
        for tenant_key, tenant_name, patients in hospitals:
            tenant_id = stable_id('tenant', tenant_key)
            if db.get(Tenant, tenant_id) is None:
                db.add(Tenant(id=tenant_id, name=tenant_name))
                created['tenants'] += 1
            db.flush()
            for external_id, tz, consent in patients:
                patient_id = stable_id('patient', external_id)
                if db.get(Patient, patient_id) is None:
                    db.add(Patient(id=patient_id, tenant_id=tenant_id,
                                   external_id=external_id, timezone=tz, consent_active=consent))
                    created['patients'] += 1
                db.flush()
                device_id = stable_id('device', external_id)
                device = db.get(Device, device_id)
                if device is None:
                    token = generate_device_token()
                    db.add(Device(id=device_id, tenant_id=tenant_id,
                                  patient_id=patient_id, token_hash=hash_device_token(token)))
                    issued_tokens.append((external_id, str(device_id), token))
                    created['devices'] += 1
                db.flush()

                # Synthetic readings; intentionally abnormal readings are useful for later alert tests.
                series = [
                    ('heart_rate', 'heart-rate-baseline', 20, Decimal('72'), '/min'),
                    ('heart_rate', 'heart-rate-elevated', 12, Decimal('108'), '/min'),
                    ('spo2', 'spo2-normal', 18, Decimal('98'), '%'),
                    ('spo2', 'spo2-low-1', 9, Decimal('90'), '%'),
                    ('spo2', 'spo2-low-2', 4, Decimal('89'), '%'),
                    ('body_temp', 'temperature', 15, Decimal('37.2'), 'Cel'),
                ]
                for metric, key, minutes_ago, value, unit in series:
                    obs_id = stable_id('observation', f'{external_id}:{key}')
                    if db.get(Observation, obs_id) is not None:
                        continue
                    effective = now - timedelta(minutes=minutes_ago)
                    original = {'client_obs_id': f'seed-{external_id}-{key}',
                                'type': metric, 'effective_at': effective.isoformat(),
                                'value': str(value), 'unit': unit}
                    db.add(Observation(
                        id=obs_id, tenant_id=tenant_id, patient_id=patient_id,
                        device_id=device_id, client_obs_id=original['client_obs_id'],
                        type=metric, value=value, unit=unit,
                        original_value=value, original_unit=unit,
                        original_effective_at=effective, effective_at=effective,
                        received_at=now, clock_skew_flagged=False,
                        clock_skew_seconds=0, original_payload=original,
                    ))
                    created['observations'] += 1
        db.flush()
    print('Development seed complete:', ', '.join(f'{k}={v}' for k, v in created.items()))
    if issued_tokens:
        print('\nNEW DEVICE TOKENS (shown once; save securely; never commit):')
        for patient, device_id, token in issued_tokens:
            print(f'{patient} | device_id={device_id} | bearer_token={token}')
    else:
        print('No new device tokens generated; existing credentials unchanged.')

if __name__ == '__main__':
    main()

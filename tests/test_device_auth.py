from uuid import uuid4
from app.services.device_auth import hash_device_token, generate_device_token
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.device import Device


def test_token_generation_is_random_and_hashes():
    """
    Generate two device secrets and verify they differ, so provisioning does not reuse
    credentials. Hashing a token must produce a 64-character digest that does not contain
    the raw secret, supporting safe storage of token hashes.
    """
    first, second = generate_device_token(), generate_device_token()
    assert first != second
    assert len(hash_device_token(first)) == 64
    assert first not in hash_device_token(first)


def test_device_auth_rejects_missing_wrong_and_malformed(api_client, db_session):
    """
    Upload one valid heart-rate reading to a seeded device using three invalid credential
    forms: no Authorization header, a wrong Bearer token, and a Basic scheme. All must
    return 401. The correct Bearer token must return 200, isolating the credential check
    from payload validity.
    """
    tenant = Tenant(id=uuid4(), name="Auth Tenant")
    db_session.add(tenant)
    db_session.flush()
    patient = Patient(id=uuid4(), tenant_id=tenant.id, external_id="auth-patient")
    db_session.add(patient)
    db_session.flush()
    device = Device(id=uuid4(), tenant_id=tenant.id, patient_id=patient.id, token_hash=hash_device_token("correct-token"))
    db_session.add(device)
    db_session.flush()
    path = f"/v1/devices/{device.id}/observations:batch"
    body = {"batch_id": "auth-test", "sent_at_device": "2026-11-20T10:00:00Z", "observations": [{"client_obs_id": "auth-reading", "type": "heart_rate", "effective_at": "2026-11-20T09:50:00Z", "value": 80, "unit": "/min"}]}
    for headers in ({"Idempotency-Key": "auth"},
                    {"Idempotency-Key": "auth", "Authorization": "Bearer wrong-token"},
                    {"Idempotency-Key": "auth", "Authorization": "Basic correct-token"}):
        response = api_client.post(path, headers=headers, json=body)
        assert response.status_code == 401
    response = api_client.post(path, headers={"Idempotency-Key": "auth", "Authorization": "Bearer correct-token"}, json=body)
    assert response.status_code == 200


def test_token_cannot_upload_for_other_device(api_client, db_session):
    """
    Two devices have different valid token hashes under the same patient. Sending the first
    device's Bearer token to the second device's ingestion URL must return 401;
    authentication must bind the token to the URL device, not merely to the tenant or
    patient.
    """
    tenant = Tenant(id=uuid4(), name="Auth Scope Tenant")
    db_session.add(tenant)
    db_session.flush()
    patient = Patient(id=uuid4(), tenant_id=tenant.id, external_id="scope-patient")
    db_session.add(patient)
    db_session.flush()
    first = Device(id=uuid4(), tenant_id=tenant.id, patient_id=patient.id, token_hash=hash_device_token("first-token"))
    second = Device(id=uuid4(), tenant_id=tenant.id, patient_id=patient.id, token_hash=hash_device_token("second-token"))
    db_session.add_all([first, second])
    db_session.flush()
    body = {"batch_id": "scope-test", "sent_at_device": "2026-11-20T10:00:00Z", "observations": [{"client_obs_id": "auth-reading", "type": "heart_rate", "effective_at": "2026-11-20T09:50:00Z", "value": 80, "unit": "/min"}]}
    response = api_client.post(f"/v1/devices/{second.id}/observations:batch", headers={"Idempotency-Key": "scope", "Authorization": "Bearer first-token"}, json=body)
    assert response.status_code == 401

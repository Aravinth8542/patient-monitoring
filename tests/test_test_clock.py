from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from app import clock
from app.config import settings


def test_test_now_header_is_honored_when_enabled(monkeypatch, api_client):
    monkeypatch.setattr(settings, "test_mode", True)
    response = api_client.get("/health", headers={"X-Test-Now": "2026-11-20T15:30:00+05:30"})
    assert response.status_code == 200
    assert clock.get_current_time("2026-11-20T15:30:00+05:30") == datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)


def test_test_now_is_ignored_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "test_mode", False)
    before = clock.utc_now()
    result = clock.get_current_time("2001-01-01T00:00:00Z")
    after = clock.utc_now()
    assert before <= result <= after


@pytest.mark.parametrize("header", ["bad-date", "2026-11-20T10:00:00", ""])
def test_invalid_test_now_rejected_when_enabled(monkeypatch, api_client, header):
    monkeypatch.setattr(settings, "test_mode", True)
    response = api_client.get("/health", headers={"X-Test-Now": header})
    assert response.status_code == 422


def test_test_now_is_used_as_ingestion_receipt_time(monkeypatch, api_client, db_session):
    from uuid import uuid4
    from app.models.tenant import Tenant
    from app.models.patient import Patient
    from app.models.device import Device
    from app.services.device_auth import hash_device_token
    from app.models.observation import Observation
    from sqlalchemy import select
    monkeypatch.setattr(settings, "test_mode", True)
    tenant = Tenant(id=uuid4(), name="Clock Test Tenant")
    db_session.add(tenant)
    db_session.flush()
    patient = Patient(id=uuid4(), tenant_id=tenant.id, external_id="clock-patient")
    db_session.add(patient)
    db_session.flush()
    device = Device(id=uuid4(), tenant_id=tenant.id, patient_id=patient.id, token_hash=hash_device_token("test-device-secret"))
    db_session.add(device)
    db_session.flush()
    response = api_client.post(
        f"/v1/devices/{device.id}/observations:batch",
        headers={"Authorization": "Bearer test-device-secret", "Idempotency-Key": "test-clock-receipt", "X-Test-Now": "2026-11-20T10:00:00Z"},
        json={"batch_id": "clock-1", "sent_at_device": "2026-11-20T10:00:00Z", "observations": [
            {"client_obs_id": "clock-reading-1", "type": "heart_rate", "value": 70, "unit": "/min", "effective_at": "2026-11-20T09:59:00Z"}
        ]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] == "accepted"
    observation = db_session.execute(select(Observation).where(Observation.client_obs_id == "clock-reading-1")).scalar_one()
    assert observation.received_at == datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    assert observation.effective_at == datetime(2026, 11, 20, 9, 59, tzinfo=timezone.utc)


def test_future_event_not_eligible_until_time_catches_up():
    effective = datetime(2026, 11, 20, 10, 2, tzinfo=timezone.utc)
    assert not clock.is_eligible(effective, datetime(2026, 11, 20, 10, 1, tzinfo=timezone.utc))
    assert clock.is_eligible(effective, datetime(2026, 11, 20, 10, 2, tzinfo=timezone.utc))

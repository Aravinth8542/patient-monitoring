from uuid import UUID, uuid4
from decimal import Decimal
from sqlalchemy import select
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.device import Device
from app.models.observation import Observation
from app.services.device_auth import hash_device_token


def seed_device(db_session):
    tenant = Tenant(id=uuid4(), name="Ingestion Test Tenant")
    db_session.add(tenant)
    db_session.flush()
    patient = Patient(id=uuid4(), tenant_id=tenant.id, external_id="ingestion-patient")
    db_session.add(patient)
    db_session.flush()
    device = Device(id=UUID("11111111-1111-4111-8111-111111111111"), tenant_id=tenant.id, patient_id=patient.id, token_hash=hash_device_token("test-device-secret"))
    db_session.add(device)
    db_session.flush()
    return device



def test_batch_partial_success(api_client, db_session):
    """
    The batch contains a valid 78 bpm heart-rate observation and an invalid symptom score of
    15. The endpoint must still return HTTP 200 with two item results: accepted for the
    valid reading and rejected with validation_error for the invalid one.
    """
    seed_device(db_session)
    response = api_client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Authorization": "Bearer test-device-secret", "Idempotency-Key": "test-001"},
        json={
            "batch_id": "batch-001",
            "sent_at_device": "2026-11-19T10:15:00+05:30",
            "observations": [
                {
                    "client_obs_id": "obs-001",
                    "type": "heart_rate",
                    "effective_at": "2026-11-19T10:00:00+05:30",
                    "value": 78,
                    "unit": "/min",
                },
                {
                    "client_obs_id": "obs-002",
                    "type": "symptom_score",
                    "effective_at": "2026-11-19T10:05:00+05:30",
                    "value": 15,
                },
            ],
        },
    )

    assert response.status_code == 200

    results = response.json()["results"]

    assert len(results) == 2
    assert results[0]["status"] == "accepted"
    assert results[1]["status"] == "rejected"
    assert results[1]["reason"] == "validation_error"


def test_batch_with_malformed_items(api_client, db_session):
    """
    Submit a valid heart-rate object followed by a string and an integer instead of
    observation objects. The endpoint must report three per-item results, accepting the
    first and rejecting both malformed entries with validation_error, rather than failing
    the entire HTTP request.
    """
    seed_device(db_session)
    response = api_client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Authorization": "Bearer test-device-secret", "Idempotency-Key": "test-002"},
        json={
            "batch_id": "batch-002",
            "sent_at_device": "2026-11-19T10:15:00+05:30",
            "observations": [
                {
                    "client_obs_id": "obs-001",
                    "type": "heart_rate",
                    "effective_at": "2026-11-19T10:00:00+05:30",
                    "value": 78,
                    "unit": "/min",
                },
                "invalid observation",
                123,
            ],
        },
    )

    assert response.status_code == 200

    results = response.json()["results"]

    assert len(results) == 3
    assert results[0]["status"] == "accepted"
    assert results[1]["status"] == "rejected"
    assert results[2]["status"] == "rejected"

    assert results[1]["reason"] == "validation_error"
    assert results[2]["reason"] == "validation_error"


def test_observation_without_timezone_is_rejected(api_client, db_session):
    """
    Two heart-rate readings differ only in timestamp validity: 10:00 has no timezone offset,
    while 10:05 includes +05:30. The first must be rejected and the second accepted within
    the same batch, avoiding ambiguous event ordering.
    """
    seed_device(db_session)
    response = api_client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Authorization": "Bearer test-device-secret", "Idempotency-Key": "test-003"},
        json={
            "batch_id": "batch-003",
            "sent_at_device": "2026-11-19T10:15:00+05:30",
            "observations": [
                {
                    "client_obs_id": "obs-001",
                    "type": "heart_rate",
                    "effective_at": "2026-11-19T10:00:00",
                    "value": 78,
                    "unit": "/min",
                },
                {
                    "client_obs_id": "obs-002",
                    "type": "heart_rate",
                    "effective_at": "2026-11-19T10:05:00+05:30",
                    "value": 80,
                    "unit": "/min",
                },
            ],
        },
    )

    assert response.status_code == 200

    results = response.json()["results"]

    assert results[0]["status"] == "rejected"
    assert results[1]["status"] == "accepted"


def test_negative_heart_rate_is_rejected(api_client, db_session):
    """
    Submit a heart rate of -20 bpm. The batch request itself is processed, but the
    impossible physiological value must receive a rejected item status.
    """
    seed_device(db_session)
    response = api_client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Authorization": "Bearer test-device-secret", "Idempotency-Key": "test-004"},
        json={
            "batch_id": "batch-004",
            "sent_at_device": "2026-11-19T10:15:00+05:30",
            "observations": [
                {
                    "client_obs_id": "obs-001",
                    "type": "heart_rate",
                    "effective_at": "2026-11-19T10:00:00+05:30",
                    "value": -20,
                    "unit": "/min",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "rejected"


def test_invalid_spo2_fraction_does_not_reject_batch(api_client, db_session):
    """
    The batch includes an invalid fractional SpO2 reading and a separate valid reading. The
    invalid measurement must be rejected individually while the other reading is still
    accepted, demonstrating item-level fault isolation. The test specifically verifies
    partial acceptance rather than HTTP-level rejection.
    """
    seed_device(db_session)
    response = api_client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Authorization": "Bearer test-device-secret", "Idempotency-Key": "test-005"},
        json={
            "batch_id": "batch-005",
            "sent_at_device": "2026-11-19T10:15:00+05:30",
            "observations": [
                {
                    "client_obs_id": "obs-001",
                    "type": "spo2",
                    "effective_at": "2026-11-19T10:00:00+05:30",
                    "value": 97,
                    "unit": "1",
                },
                {
                    "client_obs_id": "obs-002",
                    "type": "spo2",
                    "effective_at": "2026-11-19T10:05:00+05:30",
                    "value": 0.97,
                    "unit": "1",
                },
            ],
        },
    )

    assert response.status_code == 200

    results = response.json()["results"]

    assert results[0]["status"] == "rejected"
    assert results[0]["reason"] == "invalid_value"
    assert results[1]["status"] == "accepted"


def test_invalid_blood_pressure_is_rejected(api_client, db_session):
    """
    Submit a blood-pressure measurement that violates the accepted value constraints. The
    API must reject that observation rather than persist invalid clinical data.
    """
    seed_device(db_session)
    response = api_client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Authorization": "Bearer test-device-secret", "Idempotency-Key": "test-006"},
        json={
            "batch_id": "batch-006",
            "sent_at_device": "2026-11-19T10:15:00+05:30",
            "observations": [
                {
                    "client_obs_id": "obs-001",
                    "type": "blood_pressure",
                    "effective_at": "2026-11-19T10:00:00+05:30",
                    "systolic": 80,
                    "diastolic": 120,
                    "unit": "mm[Hg]",
                },
                {
                    "client_obs_id": "obs-002",
                    "type": "blood_pressure",
                    "effective_at": "2026-11-19T10:05:00+05:30",
                    "systolic": 120,
                    "diastolic": 80,
                    "unit": "mm[Hg]",
                },
            ],
        },
    )

    assert response.status_code == 200

    results = response.json()["results"]

    assert results[0]["status"] == "rejected"
    assert results[1]["status"] == "accepted"

def test_persist_all_types_and_idempotent_replay(api_client, db_session):
    """
    Upload examples of all supported observation types, then retry the same observations.
    Verify that supported types are persisted once and the replay is reported as duplicate,
    rather than creating additional database rows.
    """
    device = seed_device(db_session)
    endpoint = f"/v1/devices/{device.id}/observations:batch"
    now = "2026-11-19T10:00:00+00:00"
    observations = [
        {"client_obs_id": "hr", "type": "heart_rate", "value": 80, "unit": "/min", "effective_at": now},
        {"client_obs_id": "spo2", "type": "spo2", "value": 0.97, "unit": "1", "effective_at": now},
        {"client_obs_id": "bp", "type": "blood_pressure", "systolic": 120, "diastolic": 80, "unit": "mm[Hg]", "effective_at": now},
        {"client_obs_id": "temp", "type": "body_temp", "value": 98.6, "unit": "[degF]", "effective_at": now},
        {"client_obs_id": "symptom", "type": "symptom_score", "value": 3, "effective_at": now},
        {"client_obs_id": "med", "type": "medication_taken", "medication_ref": "rx-123", "effective_at": now},
    ]
    batch = {"batch_id": "all-types", "sent_at_device": now, "observations": observations}
    headers = {"Authorization": "Bearer test-device-secret", "Idempotency-Key": "key-all-types"}
    first = api_client.post(endpoint, json=batch, headers=headers)
    assert first.status_code == 200, first.text
    assert [x["status"] for x in first.json()["results"]] == ["accepted"] * 6
    rows = db_session.execute(select(Observation).where(Observation.device_id == device.id)).scalars().all()
    assert len(rows) == 6
    by_type = {r.type: r for r in rows}
    assert by_type["spo2"].value == Decimal("97")
    assert by_type["spo2"].original_value == Decimal("0.97")
    assert by_type["body_temp"].value == Decimal("37")
    assert by_type["blood_pressure"].systolic == Decimal("120")
    assert by_type["medication_taken"].medication_ref == "rx-123"

    replay = api_client.post(endpoint, json=batch, headers=headers)
    assert replay.status_code == 200
    assert replay.json() == first.json()

    conflicting_request = {**batch, "batch_id": "different"}
    conflict = api_client.post(endpoint, json=conflicting_request, headers=headers)
    assert conflict.status_code == 409

    duplicate = api_client.post(endpoint, json=batch, headers={"Authorization": "Bearer test-device-secret", "Idempotency-Key": "another-key"})
    assert [x["status"] for x in duplicate.json()["results"]] == ["duplicate"] * 6

    changed = {**batch, "observations": [{**observations[0], "value": 99}]}
    changed_response = api_client.post(endpoint, json=changed, headers={"Authorization": "Bearer test-device-secret", "Idempotency-Key": "third-key"})
    assert changed_response.json()["results"][0]["reason"] == "conflicting_duplicate"
    assert len(db_session.execute(select(Observation).where(Observation.device_id == device.id)).scalars().all()) == 6


def test_unknown_device_is_not_accepted(api_client):
    """
    Post an ingestion batch to a device ID that does not exist. Even with a request body and
    authorization header, the endpoint must return 401 rather than accept data for an
    unregistered device.
    """
    response = api_client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Authorization": "Bearer test-device-secret", "Idempotency-Key": "unknown"},
        json={"batch_id": "b", "sent_at_device": "2026-11-19T10:00:00Z", "observations": ["bad"]},
    )
    assert response.status_code == 401

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_batch_partial_success():
    response = client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Idempotency-Key": "test-001"},
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


def test_batch_with_malformed_items():
    response = client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Idempotency-Key": "test-002"},
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


def test_observation_without_timezone_is_rejected():
    response = client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Idempotency-Key": "test-003"},
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


def test_negative_heart_rate_is_rejected():
    response = client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Idempotency-Key": "test-004"},
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


def test_invalid_spo2_fraction_does_not_reject_batch():
    response = client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Idempotency-Key": "test-005"},
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


def test_invalid_blood_pressure_is_rejected():
    response = client.post(
        "/v1/devices/11111111-1111-4111-8111-111111111111/observations:batch",
        headers={"Idempotency-Key": "test-006"},
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
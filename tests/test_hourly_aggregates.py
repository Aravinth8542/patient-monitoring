"""Hourly rollups are persisted from accepted ingestion, not duplicate replay."""
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import select
from app.models.observation import Observation
from app.models.hourly_aggregate import HourlyAggregate
from tests.test_ingestion import seed_device


def post_readings(client, device_id, key, readings):
    return client.post(f'/v1/devices/{device_id}/observations:batch',
        headers={'Authorization': 'Bearer test-device-secret', 'Idempotency-Key': key},
        json={'batch_id': key, 'sent_at_device': '2026-11-19T10:15:00+05:30',
              'observations': readings})


def reading(obs_id, time, value):
    return {'client_obs_id': obs_id, 'type': 'heart_rate', 'effective_at': time,
            'value': value, 'unit': '/min'}


def test_hourly_aggregate_late_reading_and_duplicate(api_client, db_session):
    device = seed_device(db_session)
    first = reading('h1', '2026-11-19T10:05:00+05:30', 70)
    second = reading('h2', '2026-11-19T10:20:00+05:30', 90)
    late = reading('h3', '2026-11-19T10:10:00+05:30', 80)
    assert post_readings(api_client, device.id, 'hourly-1', [first, second]).status_code == 200
    assert post_readings(api_client, device.id, 'hourly-2', [late]).status_code == 200
    assert post_readings(api_client, device.id, 'hourly-3', [late]).json()['results'][0]['status'] == 'duplicate'

    rows = db_session.scalars(select(HourlyAggregate).where(
        HourlyAggregate.tenant_id == device.tenant_id,
        HourlyAggregate.patient_id == device.patient_id,
        HourlyAggregate.type == 'heart_rate')).all()
    # Buckets follow stored effective_at, including clock-skew correction.
    observations = db_session.scalars(select(Observation).where(
        Observation.device_id == device.id, Observation.type == 'heart_rate')).all()
    expected = {}
    for obs in observations:
        bucket = obs.effective_at.replace(minute=0, second=0, microsecond=0)
        expected.setdefault(bucket, []).append(obs.value)
    assert len(observations) == 3
    assert len(rows) == len(expected)
    for row in rows:
        values = expected[row.bucket_start]
        assert row.count == len(values)
        assert row.value_sum == sum(values)
        assert row.value_min == min(values)
        assert row.value_max == max(values)
        assert row.value_avg == sum(values) / len(values)


def test_hourly_aggregate_ignores_rejected_items(api_client, db_session):
    device = seed_device(db_session)
    ok = reading('ok', '2026-11-19T10:05:00+05:30', 70)
    bad = reading('bad', '2026-11-19T10:07:00+05:30', -100)
    result = post_readings(api_client, device.id, 'hourly-reject', [ok, bad])
    assert result.status_code == 200
    assert [item['status'] for item in result.json()['results']] == ['accepted', 'rejected']
    rows = db_session.scalars(select(HourlyAggregate).where(
        HourlyAggregate.patient_id == device.patient_id)).all()
    assert len(rows) == 1
    assert rows[0].count == 1
    assert rows[0].value_sum == Decimal('70')

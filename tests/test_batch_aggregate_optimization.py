
"""Regression tests for batch-level aggregate refresh optimization."""

from datetime import timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.observation import Observation
from app.models.hourly_aggregate import HourlyAggregate
from app.models.daily_aggregate import DailyAggregate
from tests.test_ingestion import seed_device


def post_batch(client, device_id, key, observations):
    return client.post(
        f"/v1/devices/{device_id}/observations:batch",
        headers={
            "Authorization": "Bearer test-device-secret",
            "Idempotency-Key": key,
        },
        json={
            "batch_id": key,
            "sent_at_device": "2026-11-19T10:15:00+05:30",
            "observations": observations,
        },
    )


def reading(obs_id, metric, effective_at, value, unit=None):
    item = {
        "client_obs_id": obs_id,
        "type": metric,
        "effective_at": effective_at,
        "value": value,
    }
    if unit is not None:
        item["unit"] = unit
    return item


def check_aggregates(db, device, model, granularity):
    observations = db.scalars(
        select(Observation).where(
            Observation.device_id == device.id,
            Observation.type.in_(["symptom_score", "body_temp"]),
        )
    ).all()

    expected = {}

    for observation in observations:
        effective = observation.effective_at.astimezone(timezone.utc)

        if granularity == "hour":
            bucket = effective.replace(
                minute=0, second=0, microsecond=0
            )
        else:
            bucket = effective.replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        key = (observation.type, bucket)
        expected.setdefault(key, []).append(observation.value)

    aggregates = db.scalars(
        select(model).where(
            model.tenant_id == device.tenant_id,
            model.patient_id == device.patient_id,
            model.type.in_(["symptom_score", "body_temp"]),
        )
    ).all()

    assert len(aggregates) == len(expected)

    for aggregate in aggregates:
        key = (aggregate.type, aggregate.bucket_start)
        assert key in expected

        values = expected[key]

        assert aggregate.count == len(values)
        assert aggregate.value_sum == sum(values)
        assert aggregate.value_min == min(values)
        assert aggregate.value_max == max(values)
        assert aggregate.value_avg == (
            sum(values) / Decimal(len(values))
        )


def test_mixed_metrics_and_multiple_time_buckets(
    api_client, db_session
):
    """
    A single batch includes symptom scores 2, 4, 6 and 3 across two hours and two dates,
    plus temperatures 37 and 38 in the same hour. Every item should be accepted; the shared
    aggregate checker verifies that hourly and daily buckets are separated by metric and
    effective timestamp, with correct totals and counts.
    """
    device = seed_device(db_session)

    observations = [
        reading(
            "sym-1", "symptom_score",
            "2026-11-19T10:05:00+05:30", 2
        ),
        reading(
            "sym-2", "symptom_score",
            "2026-11-19T10:15:00+05:30", 4
        ),
        reading(
            "sym-3", "symptom_score",
            "2026-11-19T09:05:00+05:30", 6
        ),
        reading(
            "sym-4", "symptom_score",
            "2026-11-18T05:45:00+05:30", 3
        ),
        reading(
            "temp-1", "body_temp",
            "2026-11-19T10:10:00+05:30", 37, "Cel"
        ),
        reading(
            "temp-2", "body_temp",
            "2026-11-19T10:20:00+05:30", 38, "Cel"
        ),
    ]

    response = post_batch(
        api_client, device.id, "mixed-buckets", observations
    )

    assert response.status_code == 200, response.text
    assert all(
        item["status"] == "accepted"
        for item in response.json()["results"]
    ), response.json()["results"]

    check_aggregates(db_session, device, HourlyAggregate, "hour")
    check_aggregates(db_session, device, DailyAggregate, "day")


def test_late_arrival_and_duplicate_do_not_corrupt_aggregates(
    api_client, db_session
):
    """
    A symptom score of 2 at 10:20 is uploaded first; a score of 8 timestamped 10:05 arrives
    later. Both must contribute to the correct historical hour and day. Re-uploading the
    10:05 event must return 'duplicate', leave aggregate statistics unchanged, and keep
    exactly two observations.
    """
    device = seed_device(db_session)

    first = reading(
        "first", "symptom_score",
        "2026-11-19T10:20:00+05:30", 2
    )

    late = reading(
        "late", "symptom_score",
        "2026-11-19T10:05:00+05:30", 8
    )

    response = post_batch(
        api_client, device.id, "initial-batch", [first]
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "accepted"

    response = post_batch(
        api_client, device.id, "late-batch", [late]
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "accepted"

    check_aggregates(db_session, device, HourlyAggregate, "hour")
    check_aggregates(db_session, device, DailyAggregate, "day")

    response = post_batch(
        api_client, device.id, "duplicate-batch", [late]
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "duplicate"

    check_aggregates(db_session, device, HourlyAggregate, "hour")
    check_aggregates(db_session, device, DailyAggregate, "day")

    stored = db_session.scalars(
        select(Observation).where(
            Observation.device_id == device.id
        )
    ).all()

    assert len(stored) == 2


from unittest.mock import patch
from app.routers import ingestion


def test_batch_refreshes_each_bucket_once(api_client, db_session):
    """
    Fifty symptom-score readings are uploaded at the same effective time, with values
    cycling from 0 through 10. The test intercepts SQL calls to the hourly and daily refresh
    procedures: despite fifty accepted observations, each affected bucket should be
    refreshed only once. Aggregate contents are then checked for correctness.
    """
    device = seed_device(db_session)

    observations = [
        reading(
            f"efficiency-{index}",
            "symptom_score",
            "2026-11-19T10:05:00+05:30",
            index % 11,
        )
        for index in range(50)
    ]

    original_execute = db_session.execute
    refresh_calls = []

    def tracked_execute(statement, *args, **kwargs):
        sql = str(statement)

        if "app_refresh_device_hourly" in sql:
            refresh_calls.append("hourly")
        elif "app_refresh_device_daily" in sql:
            refresh_calls.append("daily")

        return original_execute(statement, *args, **kwargs)

    with patch.object(db_session, "execute", side_effect=tracked_execute):
        response = post_batch(
            api_client,
            device.id,
            "efficiency-test",
            observations,
        )

    assert response.status_code == 200, response.text
    assert all(
        item["status"] == "accepted"
        for item in response.json()["results"]
    ), response.json()["results"]

    assert refresh_calls.count("hourly") == 1
    assert refresh_calls.count("daily") == 1

    check_aggregates(db_session, device, HourlyAggregate, "hour")
    check_aggregates(db_session, device, DailyAggregate, "day")
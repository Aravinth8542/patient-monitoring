
"""Simulate devices reconnecting with six hours of buffered readings.

Run only against the local patient_monitoring development database.
"""

import argparse
import asyncio
import json
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import SessionLocal
from app.models.observation import Observation
from app.models.hourly_aggregate import HourlyAggregate
from app.models.daily_aggregate import DailyAggregate


def percentile(values, percent):
    if not values:
        return 0.0
    values = sorted(values)
    position = (len(values) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] * (upper - position) + values[upper] * (position - lower)


async def send_batch(client, device, run_id, index, batch_size, now, semaphore):
    key = f"storm-{run_id}-{index}"
    observations = []

    # Spread readings over the preceding six hours.
    for item in range(batch_size):
        minutes_ago = 1 + ((index * batch_size + item) % 360)
        effective_at = now - timedelta(minutes=minutes_ago)

        observations.append({
            "client_obs_id": f"{key}-{item}",
            "type": "symptom_score",
            "value": 2,
            "effective_at": effective_at.isoformat(),
        })

    payload = {
        "batch_id": key,
        "sent_at_device": now.isoformat(),
        "observations": observations,
    }

    async with semaphore:
        started = time.perf_counter()

        try:
            response = await client.post(
                f"/v1/devices/{device['device_id']}/observations:batch",
                headers={
                    "Authorization": f"Bearer {device['token']}",
                    "Idempotency-Key": key,
                },
                json=payload,
            )
            latency = (time.perf_counter() - started) * 1000

            if response.status_code != 200:
                return response.status_code, Counter(), latency, response.text[:300]

            results = response.json().get("results", [])
            statuses = Counter(item.get("status") for item in results)

            if len(results) != batch_size:
                return 200, statuses, latency, "Unexpected result count"

            return 200, statuses, latency, None

        except httpx.RequestError as exc:
            latency = (time.perf_counter() - started) * 1000
            return None, Counter(), latency, type(exc).__name__


def verify(run_id, expected):
    """Verify the run's rows and all aggregate buckets touched by them."""

    with SessionLocal() as db:
        rows = db.scalars(
            select(Observation).where(
                Observation.client_obs_id.like(f"storm-{run_id}-%")
            )
        ).all()

        if len(rows) != expected:
            raise AssertionError(
                f"Persisted {len(rows)} observations; expected {expected}"
            )

        for model, hours in ((HourlyAggregate, 1), (DailyAggregate, 24)):
            touched = set()

            for row in rows:
                effective = row.effective_at.astimezone(timezone.utc)

                if hours == 1:
                    bucket = effective.replace(
                        minute=0, second=0, microsecond=0
                    )
                else:
                    bucket = effective.replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )

                touched.add((
                    row.tenant_id, row.patient_id, row.type, bucket
                ))

            for tenant_id, patient_id, metric, bucket in touched:
                end = bucket + timedelta(hours=hours)

                actual_count, actual_sum = db.execute(
                    select(
                        func.count(Observation.id),
                        func.sum(Observation.value),
                    ).where(
                        Observation.tenant_id == tenant_id,
                        Observation.patient_id == patient_id,
                        Observation.type == metric,
                        Observation.effective_at >= bucket,
                        Observation.effective_at < end,
                    )
                ).one()

                aggregate = db.scalar(
                    select(model).where(
                        model.tenant_id == tenant_id,
                        model.patient_id == patient_id,
                        model.type == metric,
                        model.bucket_start == bucket,
                    )
                )

                if aggregate is None:
                    raise AssertionError(
                        f"Missing {model.__tablename__}: {bucket}"
                    )

                if (
                    aggregate.count != actual_count
                    or aggregate.value_sum != actual_sum
                ):
                    raise AssertionError(
                        f"{model.__tablename__} mismatch at {bucket}: "
                        f"expected ({actual_count}, {actual_sum}), "
                        f"got ({aggregate.count}, {aggregate.value_sum})"
                    )

            print(
                f"{model.__tablename__}: "
                f"{len(touched)} buckets verified"
            )


async def run(args):
    database = make_url(settings.database_url).database
    if database != "patient_monitoring":
        raise SystemExit(
            "Refusing to run outside the development patient_monitoring database"
        )

    devices = json.loads(Path(args.devices).read_text(encoding="utf-8"))

    if not isinstance(devices, list) or not devices:
        raise SystemExit("No load-test devices configured")

    for device in devices:
        uuid.UUID(device["device_id"])
        if not device.get("token"):
            raise SystemExit("Missing device token")

    run_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    semaphore = asyncio.Semaphore(args.concurrency)

    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )

    print("\n=== RECONNECT STORM ===")
    print(f"Devices: {len(devices)}")
    print(f"Requests: {args.requests}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Batch size: {args.batch_size}")
    print(f"Backlog window: 6 hours")
    print(f"Expected observations: {args.requests * args.batch_size}")

    async with httpx.AsyncClient(
        base_url=args.url.rstrip("/"),
        timeout=httpx.Timeout(120.0),
        limits=limits,
    ) as client:
        started = time.perf_counter()

        results = await asyncio.gather(*(
            send_batch(
                client,
                devices[index % len(devices)],
                run_id,
                index,
                args.batch_size,
                now,
                semaphore,
            )
            for index in range(args.requests)
        ))

        duration = time.perf_counter() - started

    http_counts = Counter()
    observation_counts = Counter()
    errors = []
    latencies = []

    for status, counts, latency, error in results:
        http_counts[status] += 1
        observation_counts.update(counts)
        latencies.append(latency)

        if error:
            errors.append(error)

    submitted = args.requests * args.batch_size
    accepted = observation_counts["accepted"]

    print(f"\nDuration: {duration:.2f} seconds")
    print(f"Throughput: {accepted / duration:.2f} observations/sec")
    print(f"P50 latency: {percentile(latencies, 50):.2f} ms")
    print(f"P95 latency: {percentile(latencies, 95):.2f} ms")
    print(f"P99 latency: {percentile(latencies, 99):.2f} ms")
    print(f"HTTP results: {dict(http_counts)}")
    print(f"Observation results: {dict(observation_counts)}")
    print(f"Errors: {errors[:5]}")

    if (
        http_counts[200] != args.requests
        or accepted != submitted
        or errors
    ):
        raise SystemExit("RESULT: FAIL — ingestion")

    print("\nVerifying database aggregates...")
    verify(run_id, submitted)

    print("\nRESULT: PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--devices", default="load-devices.json")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=50)

    args = parser.parse_args()

    if min(args.requests, args.concurrency, args.batch_size) < 1:
        parser.error("All numeric arguments must be positive")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()

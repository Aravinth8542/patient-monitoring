
"""Concurrent ingestion correctness test against the local development API."""

import argparse
import asyncio
import json
import uuid
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models.observation import Observation
from app.models.hourly_aggregate import HourlyAggregate
from app.models.daily_aggregate import DailyAggregate


async def send_batch(client, device, run_id, index, batch_size, timestamp):
    key = f"concurrency-{run_id}-{index}"
    observations = [
        {
            "client_obs_id": f"{key}-{item}",
            "type": "symptom_score",
            "value": 2,
            "effective_at": timestamp,
        }
        for item in range(batch_size)
    ]

    try:
        response = await client.post(
            f"/v1/devices/{device['device_id']}/observations:batch",
            headers={
                "Authorization": f"Bearer {device['token']}",
                "Idempotency-Key": key,
            },
            json={
                "batch_id": key,
                "sent_at_device": timestamp,
                "observations": observations,
            },
        )

        if response.status_code != 200:
            return {
                "status": response.status_code,
                "accepted": 0,
                "error": response.text[:300],
            }

        results = response.json().get("results", [])
        statuses = Counter(item.get("status") for item in results)

        return {
            "status": 200,
            "accepted": statuses["accepted"],
            "error": None if statuses == {"accepted": batch_size}
                     else str(dict(statuses)),
        }

    except httpx.RequestError as exc:
        return {
            "status": None,
            "accepted": 0,
            "error": type(exc).__name__,
        }


def verify_aggregates(run_id, expected_count):
    """Compare affected aggregate buckets against all stored observations."""

    with SessionLocal() as db:
        run_rows = db.scalars(
            select(Observation).where(
                Observation.client_obs_id.like(
                    f"concurrency-{run_id}-%"
                )
            )
        ).all()

        if len(run_rows) != expected_count:
            raise AssertionError(
                f"Expected {expected_count} persisted observations, "
                f"found {len(run_rows)}"
            )

        for model, interval in (
            (HourlyAggregate, timedelta(hours=1)),
            (DailyAggregate, timedelta(days=1)),
        ):
            touched = set()

            for observation in run_rows:
                effective = observation.effective_at.astimezone(timezone.utc)

                if interval == timedelta(hours=1):
                    bucket = effective.replace(
                        minute=0, second=0, microsecond=0
                    )
                else:
                    bucket = effective.replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )

                touched.add((
                    observation.tenant_id,
                    observation.patient_id,
                    observation.type,
                    bucket,
                ))

            for tenant_id, patient_id, metric, bucket in touched:
                end = bucket + interval

                count, total = db.execute(
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

                aggregate = db.execute(
                    select(model).where(
                        model.tenant_id == tenant_id,
                        model.patient_id == patient_id,
                        model.type == metric,
                        model.bucket_start == bucket,
                    )
                ).scalar_one_or_none()

                if aggregate is None:
                    raise AssertionError(
                        f"Missing {model.__tablename__} bucket {bucket}"
                    )

                if aggregate.count != count or aggregate.value_sum != total:
                    raise AssertionError(
                        f"Incorrect {model.__tablename__} bucket {bucket}: "
                        f"expected count={count}, sum={total}; "
                        f"actual count={aggregate.count}, "
                        f"sum={aggregate.value_sum}"
                    )

            print(
                f"{model.__tablename__}: "
                f"{len(touched)} affected buckets verified"
            )


async def run(args):
    from sqlalchemy.engine import make_url

    database_name = make_url(settings.database_url).database

    if database_name != "patient_monitoring":
        raise SystemExit(
            "Refusing to verify against an unexpected database"
        )

    devices = json.loads(
        Path(args.devices).read_text(encoding="utf-8")
    )

    if not isinstance(devices, list) or not devices:
        raise SystemExit("No devices configured")

    for device in devices:
        uuid.UUID(device["device_id"])
        if not device.get("token"):
            raise SystemExit("Missing device token")

    run_id = uuid.uuid4().hex
    timestamp = datetime.now(timezone.utc).isoformat()

    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )

    async with httpx.AsyncClient(
        base_url=args.url,
        timeout=httpx.Timeout(120.0),
        limits=limits,
    ) as client:
        semaphore = asyncio.Semaphore(args.concurrency)

        async def limited_send(index):
            async with semaphore:
                return await send_batch(
                    client,
                    devices[index % len(devices)],
                    run_id,
                    index,
                    args.batch_size,
                    timestamp,
                )

        results = await asyncio.gather(
            *(limited_send(index) for index in range(args.requests))
        )

    http_counts = Counter(result["status"] for result in results)
    accepted = sum(result["accepted"] for result in results)
    expected = args.requests * args.batch_size
    errors = [result for result in results if result["error"]]

    print("\n=== CONCURRENT INGESTION TEST ===")
    print(f"Devices: {len(devices)}")
    print(f"Requests: {args.requests}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Submitted observations: {expected}")
    print(f"Accepted observations: {accepted}")
    print(f"HTTP results: {dict(http_counts)}")
    print(f"Request failures: {len(errors)}")

    for error in errors[:5]:
        print(f"Failure: {error}")

    if errors or accepted != expected:
        raise SystemExit("RESULT: FAIL — ingestion errors")

    print("\nVerifying persisted observations and aggregates...")
    verify_aggregates(run_id, expected)

    print("\nRESULT: PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--devices", default="load-devices.json")
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()

    if min(args.requests, args.concurrency, args.batch_size) < 1:
        parser.error("All numeric arguments must be positive")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()

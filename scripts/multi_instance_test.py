"""Two-API-instance concurrency demonstration against one shared PostgreSQL DB.

Run only against disposable synthetic test data. No database rows are deleted.
"""
import argparse
import asyncio
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select

from sqlalchemy.engine import make_url

# Explicitly bind database assertions/provisioning to the isolated test DB.
# Set this before importing app.config or app.database.
from pydantic_settings import BaseSettings, SettingsConfigDict

class _DbSettings(BaseSettings):
    database_url: str
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

original_url = make_url(_DbSettings().database_url)
if original_url.get_backend_name() != "postgresql":
    raise SystemExit("PostgreSQL required")
if original_url.database != "patient_monitoring":
    raise SystemExit("Unexpected database name; refusing to run")
if original_url.port not in (5433, 5434):
    raise SystemExit("Unexpected database port; refusing to run")
os.environ["DATABASE_URL"] = original_url.set(host="127.0.0.1", port=5434).render_as_string(hide_password=False)

from app.database import SessionLocal
from app.models.alert import Alert
from app.models.device import Device
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.services.device_auth import generate_device_token, hash_device_token
from app.models.observation import Observation
from app.models.hourly_aggregate import HourlyAggregate
from app.models.daily_aggregate import DailyAggregate


async def post(client, url, device, key, timestamp, observations):
    response = await client.post(
        f"{url.rstrip('/')}/v1/devices/{device['device_id']}/observations:batch",
        headers={"Authorization": f"Bearer {device['token']}",
                 "Idempotency-Key": key},
        json={"batch_id": key, "sent_at_device": timestamp,
              "observations": observations},
    )
    response.raise_for_status()
    return response.json()["results"]


def statuses(results):
    return Counter(item["status"] for item in results)


async def run(args):
    # Fail closed unless this is the isolated Compose test database.
    if make_url(os.environ["DATABASE_URL"]).port != 5434:
        raise SystemExit("Refusing to write outside isolated test DB on port 5434")
    run_id = uuid.uuid4().hex
    token = generate_device_token()
    with SessionLocal.begin() as db:
        tenant = db.scalar(select(Tenant).limit(1))
        if tenant is None:
            raise SystemExit("Test database has not been seeded")
        patient_id = uuid.uuid4()
        device_id = uuid.uuid4()
        db.add(Patient(
            id=patient_id, tenant_id=tenant.id,
            external_id=f"CONCURRENCY-{run_id}",
            timezone="UTC", consent_active=True,
        ))
        db.flush()
        db.add(Device(
            id=device_id, tenant_id=tenant.id, patient_id=patient_id,
            token_hash=hash_device_token(token),
        ))
        tenant_id = tenant.id
    device = {"device_id": str(device_id), "token": token}
    print("Fresh synthetic test patient:", patient_id)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = now.isoformat()
    urls = [args.url1, args.url2]

    async with httpx.AsyncClient(timeout=120) as client:
        health = await asyncio.gather(
            *(client.get(url.rstrip("/") + "/health") for url in urls)
        )
        if any(r.status_code != 200 for r in health):
            raise AssertionError("Both API instances must be healthy")

        # Same payload and idempotency key sent simultaneously to BOTH processes.
        duplicate_key = f"multi-{run_id}-same"
        duplicate_rows = [
            {"client_obs_id": f"multi-{run_id}-same-{i}",
             "type": "symptom_score", "value": 2,
             "effective_at": stamp}
            for i in range(5)
        ]
        same = await asyncio.gather(*(
            post(client, url, device, duplicate_key, stamp, duplicate_rows)
            for url in urls
        ))
        if any(len(result) != 5 for result in same):
            raise AssertionError("Unexpected duplicate-batch response size")
        # A retry of an idempotency key returns its original response body,
        # which may say 'accepted'; persistence is the actual correctness check.
        print("Same-key concurrent responses:", [dict(statuses(r)) for r in same])

        # Different requests race on the same patient and same aggregate bucket.
        unique_batches = args.batches
        async def send_unique(i):
            key = f"multi-{run_id}-unique-{i}"
            rows = [
                {"client_obs_id": f"{key}-{j}",
                 "type": "symptom_score", "value": 2,
                 "effective_at": stamp}
                for j in range(args.batch_size)
            ]
            return await post(client, urls[i % 2], device, key, stamp, rows)

        results = await asyncio.gather(
            *(send_unique(i) for i in range(unique_batches))
        )
        if any(statuses(r) != {"accepted": args.batch_size} for r in results):
            raise AssertionError(f"Unique batch rejected: {[dict(statuses(r)) for r in results]}")
        print("Unique batches accepted:", unique_batches)

        # Three low-SpO2 observations spanning 12 minutes form one default
        # sustained-threshold episode; send the identical batch to both APIs.
        alert_key = f"multi-{run_id}-alert"
        alert_rows = [
            {"client_obs_id": f"multi-{run_id}-spo2-{i}",
             "type": "spo2", "value": 90, "unit": "%",
             "effective_at": (now - timedelta(minutes=12 - i * 6)).isoformat()}
            for i in range(3)
        ]
        alert_results = await asyncio.gather(*(
            post(client, url, device, alert_key, stamp, alert_rows)
            for url in urls
        ))
        print("Alert-trigger concurrent responses:",
              [dict(statuses(r)) for r in alert_results])

    expected = 5 + unique_batches * args.batch_size + 3
    with SessionLocal() as db:
        stored = db.scalars(select(Observation).where(
            Observation.client_obs_id.like(f"multi-{run_id}-%"),
            Observation.device_id == uuid.UUID(device["device_id"]),
        )).all()
        if len(stored) != expected:
            raise AssertionError(f"Expected {expected} stored rows, got {len(stored)}")
        spo2 = [o for o in stored if o.type == "spo2"]
        if len(spo2) != 3:
            raise AssertionError(f"Expected 3 SpO2 rows, got {len(spo2)}")
        alerts = db.scalars(select(Alert).where(
            Alert.tenant_id == tenant_id,
            Alert.patient_id == patient_id,
            Alert.rule == "low_spo2",
        )).all()
        if len(alerts) != 1:
            raise AssertionError(f"Expected 1 low_spo2 episode, got {len(alerts)}")
        print("Persisted observations:", len(stored))
        print("low_spo2 alert episodes:", len(alerts))

    # Compare stored rollups with raw observations, not just expected batch sizes.
    with SessionLocal() as db:
        for model, duration in ((HourlyAggregate, timedelta(hours=1)),
                                (DailyAggregate, timedelta(days=1))):
            for metric in ("symptom_score", "spo2"):
                metric_rows = [o for o in stored if o.type == metric]
                buckets = set()
                for o in metric_rows:
                    t = o.effective_at.astimezone(timezone.utc)
                    buckets.add(t.replace(minute=0, second=0, microsecond=0)
                                if model is HourlyAggregate else
                                t.replace(hour=0, minute=0, second=0, microsecond=0))
                for bucket in buckets:
                    count, total = db.execute(select(
                        func.count(Observation.id), func.sum(Observation.value)
                    ).where(
                        Observation.tenant_id == tenant_id,
                        Observation.patient_id == patient_id,
                        Observation.type == metric,
                        Observation.effective_at >= bucket,
                        Observation.effective_at < bucket + duration,
                    )).one()
                    agg = db.scalar(select(model).where(
                        model.tenant_id == tenant_id,
                        model.patient_id == patient_id,
                        model.type == metric,
                        model.bucket_start == bucket,
                    ))
                    if agg is None or agg.count != count or agg.value_sum != total:
                        raise AssertionError(
                            f"{model.__tablename__} mismatch: {metric}, {bucket}"
                        )
            print(model.__tablename__ + ": raw-data counts/sums verified")
    print("RESULT: PASS — two instances, idempotency, aggregates, alert uniqueness")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url1", default="http://127.0.0.1:8010")
    parser.add_argument("--url2", default="http://127.0.0.1:8011")
    parser.add_argument("--batches", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args()
    if args.batches < 1 or args.batch_size < 1:
        parser.error("Batch counts must be positive and device index nonnegative")
    if args.url1.rstrip("/") != "http://127.0.0.1:8010" or args.url2.rstrip("/") != "http://127.0.0.1:8011":
        parser.error("This demo only targets the isolated test APIs on ports 8010 and 8011")
    if args.url1.rstrip("/") == args.url2.rstrip("/"):
        parser.error("Two distinct instance URLs are required")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

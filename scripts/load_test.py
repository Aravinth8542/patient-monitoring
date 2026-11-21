
"""Synthetic concurrent ingestion benchmark.

Examples:
    python -m scripts.load_test --requests 4 --concurrency 2 --batch-size 5
    python -m scripts.load_test --requests 100 --concurrency 10 --batch-size 50
"""

import argparse
import asyncio
import json
import statistics
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx


async def send_batch(
    client,
    device,
    index,
    base_url,
    semaphore,
    batch_size,
):
    unique_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()

    observations = [
        {
            "client_obs_id": f"load-{unique_id}-{i}",
            "type": "symptom_score",
            "value": 2,
            "effective_at": now,
        }
        for i in range(batch_size)
    ]

    payload = {
        "batch_id": f"load-{unique_id}",
        "sent_at_device": now,
        "observations": observations,
    }

    headers = {
        "Authorization": f"Bearer {device['token']}",
        "Idempotency-Key": f"load-{unique_id}",
    }

    async with semaphore:
        start = time.perf_counter()

        try:
            response = await client.post(
                f"{base_url}/v1/devices/{device['device_id']}/observations:batch",
                json=payload,
                headers=headers,
            )

            elapsed = (time.perf_counter() - start) * 1000

            if response.status_code == 200:
                body = response.json()
                statuses = Counter(
                    item.get("status", "unknown")
                    for item in body.get("results", [])
                )
            else:
                statuses = Counter()

            return response.status_code, elapsed, statuses, None

        except httpx.RequestError as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return None, elapsed, Counter(), type(exc).__name__


def percentile(values, percentage):
    ordered = sorted(values)

    if not ordered:
        return 0.0

    position = (len(ordered) - 1) * percentage / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower

    return (
        ordered[lower] * (1 - fraction)
        + ordered[upper] * fraction
    )


async def benchmark(args):
    devices = json.loads(
        Path(args.devices).read_text(encoding="utf-8")
    )

    if not isinstance(devices, list) or not devices:
        raise ValueError(
            "Device file must contain a nonempty JSON list"
        )

    for device in devices:
        uuid.UUID(device["device_id"])

        if not device.get("token"):
            raise ValueError(
                "Each device requires a bearer token"
            )

    semaphore = asyncio.Semaphore(args.concurrency)
    timeout = httpx.Timeout(120.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        start = time.perf_counter()

        tasks = [
            send_batch(
                client,
                devices[i % len(devices)],
                i,
                args.url.rstrip("/"),
                semaphore,
                args.batch_size,
            )
            for i in range(args.requests)
        ]

        results = await asyncio.gather(*tasks)
        duration = time.perf_counter() - start

    http_counts = Counter()
    item_counts = Counter()
    errors = Counter()
    latencies = []

    for status, latency, items, error in results:
        http_counts[status] += 1
        item_counts.update(items)
        latencies.append(latency)

        if error:
            errors[error] += 1

    submitted = args.requests * args.batch_size
    accepted = item_counts.get("accepted", 0)

    print("\n=== INGESTION LOAD TEST ===")
    print(f"Configured devices: {len(devices)}")
    print(f"Requests: {args.requests}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Batch size: {args.batch_size}")
    print(f"Total observations submitted: {submitted}")
    print(f"Duration: {duration:.2f} seconds")

    print(
        f"Request throughput: "
        f"{args.requests / duration:.2f} requests/sec"
    )

    print(
        f"Observation throughput: "
        f"{accepted / duration:.2f} observations/sec"
    )

    print(
        f"Mean latency: "
        f"{statistics.mean(latencies):.2f} ms"
    )

    print(
        f"P50 latency: "
        f"{percentile(latencies, 50):.2f} ms"
    )

    print(
        f"P95 latency: "
        f"{percentile(latencies, 95):.2f} ms"
    )

    print(
        f"P99 latency: "
        f"{percentile(latencies, 99):.2f} ms"
    )

    print(f"HTTP results: {dict(http_counts)}")
    print(f"Observation results: {dict(item_counts)}")
    print(f"Network errors: {dict(errors)}")

    if (
        http_counts.get(200, 0) != args.requests
        or accepted != submitted
        or errors
    ):
        raise SystemExit(
            "Benchmark completed with failures "
            "or non-accepted observations"
        )

    print("\nRESULT: PASS")


def main():
    parser = argparse.ArgumentParser(
        description="Concurrent synthetic ingestion load test"
    )

    parser.add_argument(
        "--devices",
        default="load-devices.json",
    )

    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000",
    )

    parser.add_argument(
        "--requests",
        type=int,
        default=20,
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
    )

    args = parser.parse_args()

    if (
        args.requests < 1
        or args.concurrency < 1
        or args.batch_size < 1
    ):
        parser.error(
            "requests, concurrency and batch-size "
            "must be positive"
        )

    asyncio.run(benchmark(args))


if __name__ == "__main__":
    main()

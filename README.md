# Remote Patient Monitoring — Backend Service

A FastAPI and PostgreSQL backend for device-originated patient observations, clinician access, time-based aggregates, alert evaluation, and FHIR R4 Observation search. Built for the Synapsis Medical backend engineering assignment.

## Features

- Authenticated bulk device ingestion with an `Idempotency-Key`, per-observation validation, duplicate handling, and original/effective/received timestamps.
- PostgreSQL tenant isolation using row-level security (RLS) and separate owner/runtime database roles.
- Staff identity and authorization, care-team access controls, consent revocation, emergency (break-glass) access, and audit records.
- Hourly and daily observation aggregates, including recomputation for delayed and out-of-order readings.
- Tenant-configurable sustained-threshold, rate-of-change, and missing-data alert rules; alert acknowledgment, resolution, and retrospective reconciliation.
- Periodic missing-data evaluation, including patients who have not yet reported observations.
- FHIR R4 Observation search and synthetic resource exports for independent validation.
- Deterministic test-clock support and scripts for concurrency and load testing.

## Stack

Python 3.12, FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL 17, Docker Compose, pytest. See `requirements.txt` for the precise Python dependencies.

## Quick start (Windows CMD)

Prerequisites: Docker Desktop with Compose and a project `.env` file. Create `.env` from `.env.example`, replace placeholder credentials, and keep `.env` private. The database owner and restricted runtime credentials must be configured as required by the database migrations.

```cmd
copy .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose ps -a
curl http://127.0.0.1:8000/health
```

Edit `.env` **before** starting Compose. The expected health response is `{"status":"healthy"}`. The `migrate` service runs Alembic and exits successfully; `db`, `api`, and `scheduler` remain running. PostgreSQL is mapped to localhost port 5433 and the API to localhost port 8000. Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

The scheduler runs the missing-data check periodically. It is a separate Compose service, not an additional public API. **Do not run `docker compose down -v` unless you intentionally want to delete the PostgreSQL volume.**

## API overview

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Health check |
| POST | `/v1/devices/{device_id}/observations:batch` | Authenticated bulk ingestion; requires `Idempotency-Key` |
| GET | `/v1/staff/me` | Authenticated staff identity |
| GET | `/v1/patients/{patient_id}` | Authorized patient lookup |
| POST | `/v1/patients/{patient_id}/consent/revoke` | Revoke consent |
| POST | `/v1/patients/{patient_id}/break-glass` | Request emergency access |
| GET | `/v1/patients/{patient_id}/aggregates/hourly` | Hourly aggregates |
| GET | `/v1/patients/{patient_id}/aggregates/daily` | Daily aggregates |
| GET | `/v1/patients/{patient_id}/rollups` | Aggregate rollups; `granularity=hour` or `day` |
| GET | `/v1/patients/{patient_id}/alerts` | Patient alerts |
| POST | `/v1/alerts/{alert_id}/acknowledge` | Acknowledge alert |
| POST | `/v1/alerts/{alert_id}/resolve` | Resolve alert |
| GET | `/v1/audit/events` | Audit event query |
| GET | `/v1/audit/verify` | Audit-chain verification |
| GET | `/fhir/Observation` | FHIR R4 Observation search |

Protected endpoints require appropriate authentication and authorization. Use `/docs` for request schemas, query parameters, and response shapes. The FHIR endpoint supports patient, code, date, sort, count, and cursor-based pagination within the implemented constraints.

## Data and alert behavior

The ingestion pipeline stores both the device-supplied and corrected effective time, as well as receipt time. Late readings update the affected hourly and daily aggregate buckets. The alert engine reevaluates affected patient histories and can retract invalidated alerts. Missing-data checks also run without new HTTP traffic and honor consent and tenant-configured windows.

Default rules are defined in `app/services/alert_rules.py`:

- `low_spo2`: sustained SpO₂ below 92, with three readings spanning at least ten minutes.
- `hr_rise`: heart-rate rise of at least 30 within 15 minutes.
- `no_data`: 24 hours without observations.

Tenants may supply their own supported rule configuration; an explicit empty list disables configured rules for that tenant.

## Verification

From the project root, with your virtual environment active and the test database configured:

```cmd
python -m pytest -q
python -m scripts.export_fhir_validation_samples
python -m scripts.concurrency_test --url http://127.0.0.1:8000 --devices load-devices.json --requests 100 --concurrency 20 --batch-size 10
python -m scripts.load_test --url http://127.0.0.1:8000 --devices load-devices.json --requests 100 --concurrency 20 --batch-size 10
```

Provision synthetic load-test devices first, if needed, with `python -m scripts.seed_load_devices`. This writes **sensitive test tokens** to `load-devices.json`; never commit or publish that file. The seeder refuses to run outside a database named `patient_monitoring` and will not overwrite an existing credentials file.

**Reported local verification (22 November 2026):** 112 pytest tests passed; a 100-request concurrency test accepted 1,000/1,000 observations with zero request failures and verified ten affected hourly and ten daily aggregate buckets. A separate 100-request load test completed in 2.99 seconds (33.48 requests/s, 334.77 observations/s, P50 483.86 ms, P95 885.12 ms, P99 932.28 ms), with all requests returning HTTP 200. These are local test results, not production capacity guarantees.

**Subsequent verification (23 November 2026):** 117 full-suite tests and 18 focused tests passed after the TEST_MODE replay change. A separate database-backed HTTP replay checked no missing-data alert at 23h59m, one at 24h, no duplicate at 25h, and tenant isolation. The Compose stack started against an existing PostgreSQL volume; clean-volume startup remains to be verified.

**Test clock:** Set `TEST_MODE=1` for the API to interpret `X-Test-Now` (ISO-8601) as effective server time for request processing. In normal mode, the scheduler independently evaluates missing-data alerts every 300 seconds. In test mode, `GET /v1/patients/{patient_id}/alerts` with `X-Test-Now` also performs a patient-scoped missing-data evaluation before reading alerts. This is a deterministic replay accommodation, not a production GET side effect. The scheduler itself uses real time and does not inherit a request header. Restore `TEST_MODE=0` after replay testing.

**AI coding tools:** ChatGPT was used to assist with architecture discussion, code review, debugging, test design, and documentation. Generated suggestions were integrated and verified using local tests and manual checks. The author remains responsible for the implementation and should be able to explain and modify it in the follow-up session.

See [VALIDATION.md](VALIDATION.md) for the reported FHIR validator results and reproduction commands, [ARCHITECTURE.md](ARCHITECTURE.md) for design notes, [docs/DATABASE.md](docs/DATABASE.md) and [docs/PYTHON_ARCHITECTURE.md](docs/PYTHON_ARCHITECTURE.md) for editable architecture diagrams, and [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for the threat model.

## Scope and limitations

**FHIR pagination concurrency limitation:** Cursor-based pagination prevents skipping or repeating existing observations when late data arrives. Receipt-time and insertion-time watermarks exclude ordinary late uploads, including uploads with identical simulated receipt timestamps. However, an observation inserted before the first page but committed afterward may appear on a subsequent page. The implementation does not provide a transaction-consistent snapshot across page requests.

**Future-dated observations:** Readings up to five minutes ahead of server time are accepted to accommodate minor device clock skew. These readings immediately contribute to aggregates but are excluded from alert evaluation until their effective timestamps. Delaying aggregation would require additional scheduled recalculation, while rejecting all future readings could discard valid data. The current approach is an intentional trade-off.

The Compose deployment runs a **single API instance**. Concurrent ingestion has been demonstrated, but multi-instance load balancing has **not** been implemented or verified. 

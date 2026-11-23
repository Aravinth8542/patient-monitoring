# Architecture and implementation notes

## Runtime topology

```text
Device client --authenticated batch--> FastAPI API --> PostgreSQL 17
Staff client  --authenticated reads--> FastAPI API --> PostgreSQL 17
                                                ^
Periodic scheduler --missing-data evaluation----|
One-shot migration container --Alembic----------|
```

Docker Compose defines `db`, `migrate`, `api`, and `scheduler`. Migrations must finish before the API and scheduler start. The database persists in the named `postgres_data` volume. This is a **single-instance API deployment**; no proxy or load balancer is included.

## Ingestion and time semantics

`POST /v1/devices/{device_id}/observations:batch` authenticates the device, establishes tenant context, checks patient consent, and processes individual observations. The `Idempotency-Key` identifies a request; reusing it with a different payload produces a conflict. Transaction-level advisory locking serializes competing requests with the same device/key. Per-observation outcomes distinguish accepted, duplicate, and rejected entries.

Stored observations retain device-supplied time, corrected effective time, and server receipt time. Aggregate refresh targets affected UTC hour/day buckets based on **persisted effective timestamps**. Delayed readings can trigger retrospective alert reevaluation.

## Security boundaries

- PostgreSQL row-level security enforces tenant boundaries on protected data.
- HTTP runtime connections use a restricted database role, distinct from the owner/migration role.
- Device and staff authorization establish database-backed tenant/identity context.
- Staff access is constrained by role and care-team assignment; consent and emergency access have explicit handling.
- Audit events support traceability and integrity checks; they are not ordinary editable application records.

Authentication tokens and database credentials must stay out of Git. The `.env.example` contains placeholders only; real values belong in `.env` or an equivalent private secret store.

## Aggregates

Hourly and daily aggregates are materialized in PostgreSQL and refreshed when accepted observations affect a bucket. Clinician endpoints enforce access checks. The `/rollups` endpoint maps `hour` and `day` to the existing hourly/daily implementation instead of maintaining a second aggregation pipeline.

## Alert evaluation

The rule engine supports sustained thresholds, rate of change, and missing data. Tenant rule configuration is stored on the tenant. Threshold/rate rules are reevaluated when relevant observations are ingested; a scheduler evaluates missing data independently of incoming requests.

Missing-data eligibility starts from the monitoring start or the latest relevant observation, as appropriate. Late observations may invalidate, shift, or preserve an existing missing-data episode. Alerts support acknowledgment and resolution; historical records remain available for review. Reconciliation avoids duplicating the same episode.

## Testing and replay

`TEST_MODE=1` enables deterministic simulated timestamps through `X-Test-Now` where supported by the application. Never enable test mode in production. Database-backed pytest coverage includes ingestion, security boundaries, aggregates, alerting, FHIR, and delayed observations. Separate scripts measure concurrent ingestion and latency. Load-test measurements are environment-specific.

## FHIR integration

`GET /fhir/Observation` returns FHIR R4 Observation search results with authorization and cursor-based pagination. The synthetic exporter writes six Observation resources and one searchset Bundle for validation without exposing real patient data. The official validator results and caveats are in `VALIDATION.md`.

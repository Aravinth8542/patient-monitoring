# Database architecture

Open `database_erd.drawio` in [diagrams.net](https://app.diagrams.net/) to inspect or edit the database diagram. It is a **logical relationship diagram**, not a literal export of every SQL foreign-key constraint. Arrows show ownership and data flow; consult the Alembic migrations for exact constraints and indexes.

## Main entities

| Area | Tables | Purpose |
|---|---|---|
| Tenant | `tenants` | Clinic boundary and tenant-specific alert rules (JSONB) |
| Enrollment | `patients`, `devices` | Patient consent, monitoring start, device association and hashed device token |
| Staff access | `staff_users`, `care_team_memberships`, `break_glass_grants` | Clinician/auditor identities, care-team authorization, temporary emergency grants |
| Ingestion | `observations`, `ingestion_requests` | Raw/canonical readings and idempotent request outcomes |
| Alerting | `alerts` | Alert episode and acknowledgment/resolution/retraction lifecycle |
| Rollups | `observation_hourly_aggregates`, `observation_daily_aggregates` | Per-patient/per-metric UTC-bucket summaries |
| Audit | `audit_events` | Append-only, tamper-evident patient access/action history |

## Reading the diagram

- `tenant_id` is the primary isolation dimension; several tables also carry `patient_id` and/or `device_id`. Database row-level security (RLS) and security-definer authorization functions enforce protected operations.
- Each device belongs to one patient. The device authenticates uploads; the staff role is separate from device authentication.
- `observations` preserves original device timestamps, corrected `effective_at`, and server `received_at`, so arrival order is not confused with event order.
- `ingestion_requests` stores the idempotency key, request fingerprint, and prior response to make retries consistent.
- Hourly/daily aggregates are derived from observations using UTC time buckets; late readings refresh affected buckets.
- `alerts` represents episodes rather than one alert per reading; historical retractions are recorded, not silently deleted.
- `audit_events` is protected by append-only controls and hash-chain integrity logic.
- `break_glass_grants` records reason and expiry for exceptional clinician access.

## Security and ownership

The API uses a restricted PostgreSQL runtime role, not the migration owner role. Authentication establishes the tenant and actor context that database policies and authorization functions use. The migration chain defines the authoritative SQL schema, policies, functions, triggers, and constraints.

## Scope note

This diagram is based on the uploaded project ZIP `patient-monitoring (17)(1).zip` and its Alembic migrations. The latest TEST_MODE replay patch affects alert evaluation behavior, not these core entities. Auxiliary private database objects, functions, triggers, and indexes are intentionally omitted from the high-level ERD for readability.

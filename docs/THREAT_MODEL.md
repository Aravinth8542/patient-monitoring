# Threat model — remote patient monitoring backend

**Scope:** Local Docker Compose deployment: FastAPI API, PostgreSQL, Alembic/seed jobs, and the independent missing-data scheduler. All data is synthetic. This is an assignment implementation, not a production security certification.

| Boundary / asset | Threat | Mitigation implemented | Residual risk / next step |
|---|---|---|---|
| Device token → ingestion API | Forged device, stolen bearer token, cross-patient upload | Device-scoped authentication, patient association and consent checks | Token theft/replay; add rotation, expiry, transport enforcement and rate limits |
| API → PostgreSQL tenant records | Cross-tenant reads or writes, missing application filter | Restricted runtime DB role, PostgreSQL RLS and database authorization context | Test all SQL paths and security-definer functions under least privilege |
| Clinician → patient data | Unauthorized care-team access, emergency access abuse | Staff authorization, care-team checks, time-limited break-glass reason and audit | Require operational review and alerts for unusual break-glass use |
| Consent → all data paths | Access after revocation | Consent checks for ingestion and patient-facing access; missing-data evaluation excludes revoked patients | Regression-test concurrent revocation, cached results, and FHIR export |
| Audit trail | Modification or deletion of access history | Append-only database controls and hash-chain verification endpoint | Privileged DB administrator can still tamper; anchor digests externally in production |
| Batch ingestion | Duplicate writes, races, malicious payloads, exhaustion | Idempotency key/fingerprint, transactional locking, validation, per-item rejection | Rate limiting, body-size caps, capacity/backpressure and saturation monitoring |
| Time and alert decisions | Clock skew, replay, out-of-order data, missing-data false positives | Original/effective/receipt times, late-data reconciliation, independent scheduler | Monitor clock drift and alert delay; TEST_MODE must remain off in production |
| FHIR export / logs | Sensitive data disclosure through export, errors or logs | Authorization and tenant/consent checks; synthetic validation fixtures | Audit every export and review logs for sensitive fields |
| Compose / local secrets | Credentials committed or exposed, database open externally | `.env` ignored, sample placeholders, localhost port bindings | Use managed secrets, TLS, patching and network isolation in production |

**Trust boundaries:** External devices and clinicians are untrusted; API authenticates them. PostgreSQL is the authoritative enforcement boundary for tenancy. Migration/seed credentials are privileged and must not be used for normal API traffic. The scheduler is trusted code but still must enforce consent and tenant-scoped processing.

**Abuse-case checks:** Attempt cross-tenant patient read and write; replay identical and conflicting batches concurrently; revoke consent before upload/export; access a patient outside the care team without and with break-glass; corrupt an audit record and run verification; submit future/old readings; verify missing-data alerts stop after revocation.

**Production priorities:** TLS, token lifecycle/rotation, structured monitoring and alerting, rate limits/backpressure, secret management, backup/restore testing, privileged-action monitoring, and independent audit-chain anchoring.

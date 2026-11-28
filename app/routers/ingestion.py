"""Batch ingestion with device authentication and request idempotency."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID
from collections import defaultdict

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.clock import get_current_time
from app.database import get_db, get_runtime_db
from app.security.tenant_context import require_device_context
from app.models.device import Device
from app.models.patient import Patient
from app.models.ingestion_request import IngestionRequest
from app.schemas.observation import BatchInput, ObservationPayload
from app.services.observation_service import process_observation
from app.services.patient_lock import lock_patient
from app.services.clock_skew import estimate_device_offset
from app.services.alert_engine import evaluate_patient_alerts
from app.services.device_auth import authenticate_device
from app.services.normalization import normalize_spo2, normalize_temperature
from app.schemas.observation import SpO2Input, BodyTempInput
from app.models.observation import Observation

router = APIRouter(prefix="/v1/devices", tags=["Ingestion"])
observation_adapter = TypeAdapter(ObservationPayload)


def request_fingerprint(batch: BatchInput) -> str:
    """Stable for JSON key ordering, but deliberately retains raw numeric forms."""
    encoded = json.dumps(batch.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def lock_idempotency_key(db: Session, device_id: UUID, key: str) -> None:
    """PostgreSQL transaction-level advisory lock serializes same device/key requests."""
    digest = hashlib.sha256(f"{device_id}:{key}".encode()).digest()
    lock_id = int.from_bytes(digest[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})


def validation_errors(exc: ValidationError) -> list[dict]:
    return [{"field": ".".join(map(str, error["loc"])),
             "message": error["msg"], "type": error["type"]}
            for error in exc.errors()]


@router.post("/{device_id}/observations:batch")
def ingest_observations(
    device_id: UUID,
    batch: BatchInput,
    request: Request,
    idempotency_key: str = Header(min_length=1, max_length=200, alias="Idempotency-Key"),
    db: Session = Depends(get_runtime_db),
    received_at: datetime = Depends(get_current_time),

    _tenant: UUID = Depends(require_device_context),
):
    # Capture once, before database lookups, for the entire batch.
    # Database authenticates token and establishes an unforgeable tenant context
    # before any table read. RLS stays active for the rest of the transaction.
    authorization = request.headers.get("Authorization")
    device = authenticate_device(db, db.get(Device, device_id), authorization)
    patient = db.get(Patient, device.patient_id)
    if patient is None or patient.tenant_id != device.tenant_id:
        raise HTTPException(status_code=404, detail="patient_not_found")
    if not patient.consent_active:
        raise HTTPException(status_code=403, detail="consent_inactive")

    fingerprint = request_fingerprint(batch)
    device_offset = estimate_device_offset(received_at, batch.sent_at_device)
    # Serialize competing requests using the same device/key until commit.
    lock_idempotency_key(db, device_id, idempotency_key)
    previous = db.execute(select(IngestionRequest).where(
        IngestionRequest.device_id == device_id,
        IngestionRequest.idempotency_key == idempotency_key,
    )).scalar_one_or_none()
    if previous is not None:
        if previous.request_hash != fingerprint:
            raise HTTPException(status_code=409, detail="idempotency_key_reused_with_different_payload")
        return previous.response_body

    # Serialize all new uploads for this patient, across devices and API instances.
    # Lock order: idempotency key, patient, aggregate buckets.
    lock_patient(db, device.tenant_id, device.patient_id)
    db.refresh(patient)
    if not patient.consent_active:
        raise HTTPException(status_code=403, detail="consent_inactive")

    results = []
    needs_alert_check = False
    accepted_ids = []
    for index, raw in enumerate(batch.observations):
        client_obs_id = raw.get("client_obs_id") if isinstance(raw, dict) else None
        try:
            observation = observation_adapter.validate_python(raw)
            if isinstance(observation, SpO2Input):
                normalize_spo2(observation.value, observation.unit)
            elif isinstance(observation, BodyTempInput):
                normalize_temperature(observation.value, observation.unit)
            status = process_observation(
                db, observation, device.tenant_id, device.patient_id, device.id,
                received_at=received_at, device_offset=device_offset,
            )
            item = {"index": index, "client_obs_id": observation.client_obs_id,
                    "status": "rejected" if status == "conflicting_duplicate" else status}
            if status == "conflicting_duplicate":
                item["reason"] = status
            results.append(item)
            if status == "accepted":
                accepted_ids.append(observation.client_obs_id)

                if observation.type.value in ("spo2", "heart_rate"):
                    needs_alert_check = True
        except ValidationError as exc:
            results.append({"index": index, "client_obs_id": client_obs_id,
                            "status": "rejected", "reason": "validation_error",
                            "errors": validation_errors(exc)})
        except ValueError as exc:
            results.append({"index": index, "client_obs_id": client_obs_id,
                            "status": "rejected", "reason": "invalid_value",
                            "errors": [{"field": "value", "message": str(exc), "type": "value_error"}]})

    if accepted_ids:
        # Ensure accepted observations are available to aggregate queries.
        db.flush()

        # The effective timestamp must come from the persisted observation,
        # because process_observation may correct the device's clock skew.
        accepted_rows = db.execute(
            select(
                Observation.client_obs_id,
                Observation.type,
                Observation.effective_at,
            ).where(
                Observation.device_id == device.id,
                Observation.client_obs_id.in_(accepted_ids),
            )
        ).all()

        hourly_buckets = {}
        daily_buckets = {}

        for obs_id, metric, effective_at in accepted_rows:
            effective_utc = effective_at.astimezone(timezone.utc)

            hour = effective_utc.replace(
                minute=0, second=0, microsecond=0
            )
            day = effective_utc.replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            hourly_buckets.setdefault((metric, hour), obs_id)
            daily_buckets.setdefault((metric, day), obs_id)

        # Owner-backed test sessions need the same device authorization context.
        # Production runtime connections already have authenticated context.
        if db.execute(text("SELECT current_user")).scalar_one() != "patient_monitoring_runtime":
            token = (authorization or "").removeprefix("Bearer ").strip()
            digest = hashlib.sha256(token.encode()).hexdigest()

            authorized_tenant = db.execute(
                text("SELECT public.app_authorize_device(:device_id, :digest)"),
                {"device_id": device.id, "digest": digest},
            ).scalar_one_or_none()

            if authorized_tenant != device.tenant_id:
                raise HTTPException(
                    status_code=401,
                    detail="invalid_device_credentials",
                )

        # Stable ordering reduces avoidable lock-order inversions.
        for bucket in sorted(hourly_buckets):
            db.execute(
                text("SELECT public.app_refresh_device_hourly(:device, :obs_id)"),
                {"device": device.id, "obs_id": hourly_buckets[bucket]},
            )

        for bucket in sorted(daily_buckets):
            db.execute(
                text("SELECT public.app_refresh_device_daily(:device, :obs_id)"),
                {"device": device.id, "obs_id": daily_buckets[bucket]},
            )
    response = {"batch_id": batch.batch_id, "results": results}
    db.add(IngestionRequest(
        device_id=device_id, idempotency_key=idempotency_key,
        request_hash=fingerprint, response_body=response, status_code=200,
        created_at=received_at,
    ))
    # Reconcile missing-data alerts for every accepted observation type.
    if accepted_ids:
        db.execute(text("SELECT public.app_reconcile_device_no_data(:tenant, :patient, :now)"),
                   {"tenant": device.tenant_id, "patient": device.patient_id, "now": received_at})
    # Evaluate after accepted readings are flushed, in the same transaction.
    # Any alert-write failure rolls back the batch rather than silently losing alerts.
    if needs_alert_check:
        evaluate_patient_alerts(db, device.tenant_id, device.patient_id,
                                received_at, device_context=(db.execute(text("SELECT current_user")).scalar_one() == "patient_monitoring_runtime"))
    db.commit()
    return response

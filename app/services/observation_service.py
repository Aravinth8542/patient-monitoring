"""Observation persistence and safe device-scoped duplicate classification."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.observation import Observation
from app.schemas.observation import (
    ObservationPayload, HeartRateInput, SpO2Input, BloodPressureInput,
    BodyTempInput, SymptomScoreInput, MedicationTakenInput,
)
from app.services.normalization import normalize_spo2, normalize_temperature
from app.services.clock_skew import resolve_effective_at

observation_adapter = TypeAdapter(ObservationPayload)
DUPLICATE_CONSTRAINT = "uq_observation_device_client_id"


def canonicalize(value):
    if isinstance(value, Decimal):
        return value.normalize()
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, dict):
        return {key: canonicalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    return value


def find_existing_observation(db: Session, device_id: UUID, client_obs_id: str) -> Observation | None:
    return db.execute(select(Observation).where(
        Observation.device_id == device_id,
        Observation.client_obs_id == client_obs_id,
    )).scalar_one_or_none()


def is_identical_observation(existing: Observation, incoming: BaseModel) -> bool:
    original = observation_adapter.validate_python(existing.original_payload)
    return canonicalize(original.model_dump(mode="python")) == canonicalize(incoming.model_dump(mode="python"))


def is_identical_heart_rate(existing: Observation, incoming: HeartRateInput) -> bool:
    return (existing.type == incoming.type.value and existing.value == incoming.value
            and existing.unit == incoming.unit and existing.original_effective_at == incoming.effective_at)


def save_observation(
    db: Session, observation: ObservationPayload, tenant_id: UUID,
    patient_id: UUID, device_id: UUID, *, received_at: datetime | None = None,
    device_offset: timedelta = timedelta(0),
) -> Observation:
    """Flush one observation; caller owns the transaction."""
    recorded_at = received_at or datetime.now(timezone.utc)
    effective_at, skew_flagged = resolve_effective_at(
        observation.effective_at, recorded_at, device_offset
    )
    skew = int(device_offset.total_seconds())
    row = Observation(
        tenant_id=tenant_id, patient_id=patient_id, device_id=device_id,
        client_obs_id=observation.client_obs_id, type=observation.type.value,
        original_effective_at=observation.effective_at, effective_at=effective_at,
        received_at=recorded_at, original_payload=observation.model_dump(mode="json"),
        clock_skew_flagged=skew_flagged,
        clock_skew_seconds=skew,
    )
    if isinstance(observation, HeartRateInput):
        row.value, row.unit = observation.value, observation.unit
        row.original_value, row.original_unit = observation.value, observation.unit
    elif isinstance(observation, SpO2Input):
        row.value = normalize_spo2(observation.value, observation.unit)
        row.unit = "%"
        row.original_value, row.original_unit = observation.value, observation.unit
    elif isinstance(observation, BloodPressureInput):
        row.systolic, row.diastolic, row.unit = observation.systolic, observation.diastolic, observation.unit
        # Full source measurement remains in original_payload.
        row.original_unit = observation.unit
    elif isinstance(observation, BodyTempInput):
        row.value = normalize_temperature(observation.value, observation.unit)
        row.unit = "Cel"
        row.original_value, row.original_unit = observation.value, observation.unit
    elif isinstance(observation, SymptomScoreInput):
        row.value = Decimal(observation.value)
        row.original_value = Decimal(observation.value)
    elif isinstance(observation, MedicationTakenInput):
        row.medication_ref = observation.medication_ref
    else:
        raise ValueError("Unsupported observation type")
    db.add(row)
    db.flush()
    return row


def save_heart_rate(db: Session, observation: HeartRateInput, tenant_id, patient_id, device_id) -> Observation:
    return save_observation(db, observation, tenant_id, patient_id, device_id)


def process_observation(
    db: Session, observation: ObservationPayload, tenant_id: UUID,
    patient_id: UUID, device_id: UUID, *, received_at: datetime | None = None,
    device_offset: timedelta = timedelta(0),
) -> str:
    existing = find_existing_observation(db, device_id, observation.client_obs_id)
    if existing is not None:
        return "duplicate" if is_identical_observation(existing, observation) else "conflicting_duplicate"
    try:
        with db.begin_nested():
            save_observation(db, observation, tenant_id, patient_id, device_id, received_at=received_at, device_offset=device_offset)
        return "accepted"
    except IntegrityError as exc:
        original = exc.orig
        if (getattr(original, "sqlstate", None) != "23505" or
                getattr(getattr(original, "diag", None), "constraint_name", None) != DUPLICATE_CONSTRAINT):
            raise
        existing = find_existing_observation(db, device_id, observation.client_obs_id)
        if existing is None:
            raise
        return "duplicate" if is_identical_observation(existing, observation) else "conflicting_duplicate"


def process_heart_rate(db: Session, observation: HeartRateInput, tenant_id, patient_id, device_id) -> str:
    return process_observation(db, observation, tenant_id, patient_id, device_id)

"""Clinician-only, consent-aware reads of effective-time summary buckets."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clock import get_current_time
from app.database import get_runtime_db
from app.security.staff_context import StaffIdentity, require_staff_context

router = APIRouter(prefix="/v1/patients", tags=["Aggregates"])

_COLUMNS = """type, bucket_start, count, value_sum, value_min, value_max, value_avg,
 systolic_sum, systolic_min, systolic_max, systolic_avg,
 diastolic_sum, diastolic_min, diastolic_max, diastolic_avg"""
_TABLES = {
    "hourly": "public.observation_hourly_aggregates",
    "daily": "public.observation_daily_aggregates",
}


def _list_aggregates(
    patient_id: UUID,
    granularity: str,
    staff: StaffIdentity,
    db: Session,
    now: datetime,
    start: datetime | None,
    end: datetime | None,
    observation_type: str | None,
    limit: int,
):
    if staff.role != "clinician":
        raise HTTPException(status_code=403, detail="clinician_role_required")
    if start is not None and (start.tzinfo is None or start.utcoffset() is None):
        raise HTTPException(status_code=422, detail="start_requires_timezone")
    if end is not None and (end.tzinfo is None or end.utcoffset() is None):
        raise HTTPException(status_code=422, detail="end_requires_timezone")
    if start is not None and end is not None and start >= end:
        raise HTTPException(status_code=422, detail="invalid_time_range")

    allowed = db.execute(text("""SELECT 1 FROM public.patients p
        WHERE p.id=:patient AND p.tenant_id=:tenant AND p.consent_active=true
          AND public.app_staff_can_read(p.id)"""),
        {"patient": patient_id, "tenant": staff.tenant_id}).scalar_one_or_none()
    if allowed is None:
        raise HTTPException(status_code=404, detail="patient_not_found")

    # Table identifier comes only from a fixed server-side mapping, never user input.
    table = _TABLES[granularity]
    conditions = ["tenant_id=:tenant", "patient_id=:patient"]
    params = {"tenant": staff.tenant_id, "patient": patient_id, "limit": limit}
    if start is not None:
        conditions.append("bucket_start >= :start")
        params["start"] = start
    if end is not None:
        conditions.append("bucket_start < :end")
        params["end"] = end
    if observation_type is not None:
        conditions.append("type = :kind")
        params["kind"] = observation_type
    where_clause = " AND ".join(conditions)
    rows = db.execute(text(f"""SELECT {_COLUMNS} FROM {table}
        WHERE {where_clause}
        ORDER BY bucket_start DESC, type ASC LIMIT :limit"""), params).mappings().all()

    if db.execute(text("SELECT public.app_staff_assigned(:patient)"),
                  {"patient": patient_id}).scalar_one():
        db.execute(text("SELECT public.app_record_staff_audit(:patient, 'patient_aggregates_read', :now)"),
                   {"patient": patient_id, "now": now})
    else:
        db.execute(text("SELECT public.app_record_emergency_read(:patient, :now)"),
                   {"patient": patient_id, "now": now})
    db.commit()  # Audit is durable before returning protected measurements.
    return {"patient_id": patient_id, "granularity": granularity,
            "aggregates": [dict(row) for row in rows]}


@router.get("/{patient_id}/aggregates/hourly")
def get_hourly_aggregates(
    patient_id: UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    observation_type: str | None = Query(default=None, alias="type", max_length=50),
    limit: int = Query(default=100, ge=1, le=500),
    staff: StaffIdentity = Depends(require_staff_context),
    db: Session = Depends(get_runtime_db),
    now: datetime = Depends(get_current_time),
):
    return _list_aggregates(patient_id, "hourly", staff, db, now, start, end, observation_type, limit)


@router.get("/{patient_id}/aggregates/daily")
def get_daily_aggregates(
    patient_id: UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    observation_type: str | None = Query(default=None, alias="type", max_length=50),
    limit: int = Query(default=100, ge=1, le=500),
    staff: StaffIdentity = Depends(require_staff_context),
    db: Session = Depends(get_runtime_db),
    now: datetime = Depends(get_current_time),
):
    return _list_aggregates(patient_id, "daily", staff, db, now, start, end, observation_type, limit)


@router.get("/{patient_id}/rollups")
def get_rollups(
    patient_id: UUID,
    metric: str | None = Query(default=None, max_length=50),
    granularity: str = Query(..., pattern="^(hour|day)$"),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    staff: StaffIdentity = Depends(require_staff_context),
    db: Session = Depends(get_runtime_db),
    now: datetime = Depends(get_current_time),
):
    """Assignment-compatible rollup endpoint; delegates to audited aggregate reads."""
    storage_granularity = {"hour": "hourly", "day": "daily"}[granularity]
    result = _list_aggregates(
        patient_id, storage_granularity, staff, db, now, start, end, metric, limit
    )
    result["granularity"] = granularity
    return result

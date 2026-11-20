"""Audited clinician-only patient metadata reads."""
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.clock import get_current_time
from app.database import get_runtime_db
from app.security.staff_context import StaffIdentity, require_staff_context

router = APIRouter(prefix="/v1/patients", tags=["Patients"])

class BreakGlassRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=500)

@router.get("/{patient_id}")
def read_assigned_patient(
    patient_id: UUID,
    staff: StaffIdentity = Depends(require_staff_context),
    db: Session = Depends(get_runtime_db),
    now: datetime = Depends(get_current_time),
):
    if staff.role != "clinician":
        raise HTTPException(status_code=403, detail="clinician_role_required")
    # Query must verify the care-team relationship, not merely tenant membership.
    row = db.execute(text("""
        SELECT p.id, p.timezone, p.consent_active
        FROM patients p
        WHERE p.id=:patient_id AND p.tenant_id=:tenant_id
          AND p.consent_active=true AND public.app_staff_can_read(p.id)
    """), {"patient_id":patient_id, "tenant_id":staff.tenant_id, "staff_id":staff.id}).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="patient_not_found")
    # Ordinary assigned reads retain the existing audit action; emergency reads are distinct.
    if db.execute(text("SELECT public.app_staff_assigned(:patient)"), {"patient": patient_id}).scalar_one():
        db.execute(text("SELECT public.app_record_staff_audit(:patient_id, 'patient_metadata_read', :now)"),
                   {"patient_id": patient_id, "now": now})
    else:
        db.execute(text("SELECT public.app_record_emergency_read(:patient_id, :now)"),
                   {"patient_id": patient_id, "now": now})
    db.commit()  # Audit must be durable before returning protected patient information.
    return {"id":row.id, "timezone":row.timezone, "consent_active":row.consent_active}

@router.post("/{patient_id}/consent:revoke")
def revoke_patient_consent(
    patient_id: UUID,
    staff: StaffIdentity = Depends(require_staff_context),
    db: Session = Depends(get_runtime_db),
    now: datetime = Depends(get_current_time),
):
    """Idempotent consent revocation; SQL function enforces care-team access and audits changes."""
    if staff.role != "clinician":
        raise HTTPException(status_code=403, detail="clinician_role_required")
    # Avoid exposing whether an unassigned or cross-tenant patient exists.
    authorized = db.execute(text("""
        SELECT 1 FROM patients p
        WHERE p.id=:patient AND p.tenant_id=:tenant
          AND public.app_staff_assigned(p.id)
    """), {"patient": patient_id, "tenant": staff.tenant_id}).scalar_one_or_none()
    if authorized is None:
        raise HTTPException(status_code=404, detail="patient_not_found")
    changed = db.execute(
        text("SELECT public.app_revoke_patient_consent(:patient,:now)"),
        {"patient": patient_id, "now": now},
    ).scalar_one()
    db.commit()
    return {"patient_id": patient_id, "consent_active": False, "changed": changed}

@router.post("/{patient_id}/break-glass")
def grant_emergency_access(
    patient_id: UUID,
    payload: BreakGlassRequest,
    staff: StaffIdentity = Depends(require_staff_context),
    db: Session = Depends(get_runtime_db),
):
    if staff.role != "clinician":
        raise HTTPException(status_code=403, detail="clinician_role_required")
    # Do not reveal cross-tenant IDs or revoked patients.
    # Unassigned patients are invisible through RLS; the grant function independently
    # checks tenant and consent, and raises an authorization error if either fails.
    try:
        with db.begin_nested():
            expires = db.execute(text("SELECT public.app_grant_break_glass(:patient,:reason)"),
                {"patient": patient_id, "reason": payload.reason}).scalar_one()
    except Exception as exc:
        from sqlalchemy.exc import DBAPIError
        if isinstance(exc, DBAPIError) and getattr(getattr(exc, "orig", None), "sqlstate", None) == "42501":
            raise HTTPException(status_code=404, detail="patient_not_found") from None
        raise
    db.commit()
    return {"patient_id": patient_id, "expires_at": expires, "reason_recorded": True}

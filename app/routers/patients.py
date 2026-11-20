"""Audited clinician-only patient metadata reads."""
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.clock import get_current_time
from app.database import get_runtime_db
from app.security.staff_context import StaffIdentity, require_staff_context

router = APIRouter(prefix="/v1/patients", tags=["Patients"])

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
        JOIN care_team_memberships c ON c.patient_id=p.id AND c.tenant_id=p.tenant_id
        WHERE p.id=:patient_id AND p.tenant_id=:tenant_id AND c.staff_id=:staff_id
          AND p.consent_active=true
    """), {"patient_id":patient_id, "tenant_id":staff.tenant_id, "staff_id":staff.id}).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="patient_not_found")
    db.execute(text("SELECT public.app_record_staff_audit(:patient_id, 'patient_metadata_read', :now)"),
               {"patient_id": patient_id, "now": now})
    db.commit()  # Audit must be durable before returning protected patient information.
    return {"id":row.id, "timezone":row.timezone, "consent_active":row.consent_active}

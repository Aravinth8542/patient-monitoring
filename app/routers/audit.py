"""Auditor-facing event metadata; never returns observations or patient payloads."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.clock import get_current_time
from app.database import get_runtime_db
from app.security.staff_context import StaffIdentity, require_staff_context

router = APIRouter(prefix="/v1/audit", tags=["Audit"])

@router.get("/events")
def audit_events(
    staff: StaffIdentity = Depends(require_staff_context),
    db: Session = Depends(get_runtime_db),
    _now: datetime = Depends(get_current_time),
    limit: int = Query(default=50, ge=1, le=100),
):
    if staff.role != 'auditor':
        raise HTTPException(status_code=403, detail='auditor_role_required')
    rows = db.execute(text("""SELECT id, actor_id, action, occurred_at
        FROM audit_events WHERE tenant_id=:tenant_id
        ORDER BY occurred_at DESC, id DESC LIMIT :limit"""),
        {"tenant_id":staff.tenant_id,"limit":limit}).all()
    db.execute(text("SELECT public.app_record_staff_audit(NULL, 'audit_events_read', :now)"),
               {"now": _now})
    db.commit()
    return {"events": [{"id":r.id,"actor_id":r.actor_id,"action":r.action,
                         "occurred_at":r.occurred_at} for r in rows]}


@router.get("/verify")
def verify_audit_chain(
    staff: StaffIdentity = Depends(require_staff_context),
    db: Session = Depends(get_runtime_db),
    now: datetime = Depends(get_current_time),
):
    if staff.role != "auditor":
        raise HTTPException(status_code=403, detail="auditor_role_required")
    verified = db.execute(text("SELECT public.app_verify_audit_chain()")).scalar_one()
    db.execute(text("SELECT public.app_record_staff_audit(NULL, 'audit_chain_verified', :now)"),
               {"now": now})
    db.commit()
    return {"valid": verified}

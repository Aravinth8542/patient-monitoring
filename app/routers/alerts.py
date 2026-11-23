"""Clinician alert listing and audited lifecycle transitions."""
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from app.clock import get_current_time
from app.database import get_runtime_db
from app.security.staff_context import StaffIdentity, require_staff_context
from app.services.test_mode_no_data import evaluate_replay_no_data

router = APIRouter(prefix='/v1', tags=['Alerts'])

@router.get('/patients/{patient_id}/alerts')
def list_patient_alerts(patient_id: UUID, staff: StaffIdentity = Depends(require_staff_context),
                        db: Session = Depends(get_runtime_db), now: datetime = Depends(get_current_time),
                        x_test_now: str | None = Header(default=None, alias="X-Test-Now")):
    if staff.role != 'clinician':
        raise HTTPException(status_code=403, detail='clinician_role_required')
    patient = db.execute(text('''SELECT 1 FROM patients WHERE id=:patient AND tenant_id=:tenant
        AND consent_active=true AND public.app_staff_can_read(id)'''),
        {'patient':patient_id,'tenant':staff.tenant_id}).scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=404, detail='patient_not_found')
    evaluate_replay_no_data(now, x_test_now is not None, staff.tenant_id, patient_id)
    rows = db.execute(text('''SELECT id,rule,severity,status,episode_start,created_at,
    acknowledged_at,acknowledged_by,resolved_at,resolved_by,
    retracted_at,retraction_reason FROM alerts
    WHERE tenant_id=:tenant AND patient_id=:patient ORDER BY episode_start DESC,id DESC'''),
    {'tenant':staff.tenant_id,'patient':patient_id}).mappings().all()
    if db.execute(
        text("SELECT public.app_staff_assigned(:patient)"),
        {"patient": patient_id},
        ).scalar_one():
        db.execute(
            text("SELECT public.app_record_staff_audit(:patient, 'patient_alerts_read', :now)"),
            {"patient": patient_id, "now": now},
        )
    else:
        db.execute(
            text("SELECT public.app_record_emergency_read(:patient, :now)"),
            {"patient": patient_id, "now": now},
        )

    db.commit()
    return {'alerts': [dict(row) for row in rows]}

def _transition(alert_id: UUID, action: str, staff: StaffIdentity, db: Session, now: datetime):
    if staff.role != 'clinician':
        raise HTTPException(status_code=403, detail='clinician_role_required')
    try:
        with db.begin_nested():
            status = db.execute(text('SELECT public.app_transition_alert(:id,:action,:now)'),
                {'id':alert_id,'action':action,'now':now}).scalar_one()
    except DBAPIError as exc:
        sqlstate = getattr(getattr(exc,'orig',None),'sqlstate',None)
        if sqlstate == '42501':
            raise HTTPException(status_code=404, detail='alert_not_found') from None
        if sqlstate == '22023':
            raise HTTPException(status_code=409, detail='invalid_alert_transition') from None
        raise
    db.commit()
    return {'id':alert_id,'status':status}

@router.post('/alerts/{alert_id}/acknowledge')
def acknowledge_alert(alert_id: UUID, staff: StaffIdentity = Depends(require_staff_context),
                      db: Session = Depends(get_runtime_db), now: datetime = Depends(get_current_time)):
    return _transition(alert_id,'acknowledge',staff,db,now)

@router.post('/alerts/{alert_id}/resolve')
def resolve_alert(alert_id: UUID, staff: StaffIdentity = Depends(require_staff_context),
                  db: Session = Depends(get_runtime_db), now: datetime = Depends(get_current_time)):
    return _transition(alert_id,'resolve',staff,db,now)

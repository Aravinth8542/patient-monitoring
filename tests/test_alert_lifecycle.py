"""Exercise lifecycle transitions through signed PostgreSQL staff context."""
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.staff import StaffUser, CareTeamMembership
from app.models.alert import Alert
from app.services.staff_auth import hash_staff_token

NOW = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)

def test_alert_acknowledge_resolve_and_audit(db_session):
    """
    An assigned clinician acts on an initially open low-SpO2 alert through the database
    transition function. Acknowledge changes the status to 'acknowledged'; acknowledging it
    again is an invalid transition and raises a database error; resolving it then succeeds.
    Both acknowledged_by and resolved_by must identify that clinician.
    """
    tenant = Tenant(id=uuid4(), name='lifecycle-' + uuid4().hex)
    db_session.add(tenant); db_session.flush()
    patient = Patient(id=uuid4(), tenant_id=tenant.id, external_id=uuid4().hex, timezone='UTC', consent_active=True)
    staff = StaffUser(id=uuid4(), tenant_id=tenant.id, role='clinician', token_hash=hash_staff_token('alert-'+uuid4().hex))
    db_session.add_all([patient,staff]); db_session.flush()
    db_session.add(CareTeamMembership(tenant_id=tenant.id,patient_id=patient.id,staff_id=staff.id))
    alert = Alert(id=uuid4(),tenant_id=tenant.id,patient_id=patient.id,rule='low_spo2',severity='high',status='open',episode_start=NOW,created_at=NOW)
    db_session.add(alert); db_session.flush()
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    db_session.execute(text('SELECT * FROM public.app_authorize_staff(:digest)'),{'digest':staff.token_hash})
    assert db_session.execute(text('SELECT public.app_transition_alert(:id,\'acknowledge\',:now)'),{'id':alert.id,'now':NOW}).scalar_one() == 'acknowledged'
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text('SELECT public.app_transition_alert(:id,\'acknowledge\',:now)'),{'id':alert.id,'now':NOW})
    assert db_session.execute(text('SELECT public.app_transition_alert(:id,\'resolve\',:now)'),{'id':alert.id,'now':NOW}).scalar_one() == 'resolved'
    row = db_session.execute(text('SELECT status,acknowledged_by,resolved_by FROM alerts WHERE id=:id'),{'id':alert.id}).one()
    assert row.status == 'resolved' and row.acknowledged_by == staff.id and row.resolved_by == staff.id

"""Database-backed signed staff identity and audit integrity."""
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.staff import StaffUser, CareTeamMembership
from app.services.staff_auth import hash_staff_token


def test_staff_context_and_append_only_audit(db_session):
    """
    After token authorization, the current staff ID matches the clinician. Manually changing
    app.staff_id to another UUID must invalidate the signed identity rather than impersonate
    someone else. The controlled audit writer can create an event, but the runtime role
    cannot read audit rows or issue UPDATE or direct INSERT statements.
    """
    tenant = Tenant(name='audit-test-' + uuid.uuid4().hex)
    # Persist the parent first: assigning UUIDs alone does not establish
    # ORM dependency ordering for a bulk flush.
    tenant.id = uuid.uuid4()
    db_session.add(tenant)
    db_session.flush()
    patient = Patient(id=uuid.uuid4(), tenant_id=tenant.id, external_id='p', timezone='UTC')
    staff = StaffUser(id=uuid.uuid4(), tenant_id=tenant.id, role='clinician',
                      token_hash=hash_staff_token('audit-test-token'))
    db_session.add_all([patient, staff])
    db_session.flush()
    db_session.add(CareTeamMembership(tenant_id=tenant.id, staff_id=staff.id, patient_id=patient.id))
    db_session.flush()
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    db_session.execute(text('SELECT * FROM public.app_authorize_staff(:digest)'),
                       {'digest': hash_staff_token('audit-test-token')})
    assert db_session.execute(text('SELECT public.app_current_staff()')).scalar_one() == staff.id
    # Caller cannot spoof another staff identity by modifying session variables.
    db_session.execute(text("SELECT set_config('app.staff_id', :id, true)"), {'id': str(uuid.uuid4())})
    assert db_session.execute(text('SELECT public.app_current_staff()')).scalar_one() is None
    db_session.execute(text('SELECT * FROM public.app_authorize_staff(:digest)'),
                       {'digest': hash_staff_token('audit-test-token')})
    event_id = db_session.execute(text("SELECT public.app_record_staff_audit(:patient, 'patient_metadata_read', :now)"),
        {'patient': patient.id, 'now': datetime.now(timezone.utc)}).scalar_one()
    assert db_session.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 0
    # The runtime role has no UPDATE privilege at all; PostgreSQL rejects it
    # before row-level security or the append-only trigger is evaluated.
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE audit_events SET action='changed' WHERE id=:id"),
                               {'id': event_id})
    # Direct writes are denied; all audit events must use the controlled writer.
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("""INSERT INTO audit_events
                (tenant_id,actor_id,patient_id,action,occurred_at)
                VALUES (:tenant,:actor,:patient,'patient_metadata_read',:now)"""),
                {'tenant':tenant.id,'actor':staff.id,'patient':patient.id,
                 'now':datetime.now(timezone.utc)})

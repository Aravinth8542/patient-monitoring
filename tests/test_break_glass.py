"""Real restricted-role emergency-access regression tests."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import text
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.staff import StaffUser
from app.services.staff_auth import hash_staff_token


def test_break_glass_temporary_and_audited(db_session):
    tenant_id, patient_id, clinician_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = 'emergency-' + uuid.uuid4().hex
    db_session.add(Tenant(id=tenant_id, name='emergency-' + uuid.uuid4().hex))
    db_session.flush()
    db_session.add(Patient(id=patient_id, tenant_id=tenant_id, external_id='emergency'))
    db_session.add(StaffUser(id=clinician_id, tenant_id=tenant_id, role='clinician', token_hash=hash_staff_token(token)))
    db_session.flush()
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    db_session.execute(text('SELECT * FROM public.app_authorize_staff(:digest)'), {'digest': hash_staff_token(token)})
    assert db_session.execute(text('SELECT count(*) FROM patients WHERE id=:id'), {'id': patient_id}).scalar_one() == 0
    expiry = db_session.execute(text('SELECT public.app_grant_break_glass(:id,:reason)'),
                                {'id': patient_id, 'reason': 'Emergency assessment required'}).scalar_one()
    assert expiry > datetime.now(timezone.utc)
    assert db_session.execute(text('SELECT count(*) FROM patients WHERE id=:id'), {'id': patient_id}).scalar_one() == 1
    db_session.execute(text('SELECT public.app_record_emergency_read(:id,:now)'),
                       {'id': patient_id, 'now': datetime.now(timezone.utc)})
    db_session.execute(text('RESET ROLE'))
    assert db_session.execute(text("SELECT count(*) FROM audit_events WHERE patient_id=:id AND action='break_glass_granted'"), {'id': patient_id}).scalar_one() == 1
    assert db_session.execute(text("SELECT count(*) FROM audit_events WHERE patient_id=:id AND action='patient_emergency_read'"), {'id': patient_id}).scalar_one() == 1
    # Privileged test setup simulates expiry without waiting fifteen minutes.
    db_session.execute(text("UPDATE break_glass_grants SET expires_at=clock_timestamp()-interval '1 second' WHERE patient_id=:id"), {'id': patient_id})
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    assert db_session.execute(text('SELECT count(*) FROM patients WHERE id=:id'), {'id': patient_id}).scalar_one() == 0


def test_break_glass_rejects_revoked_consent(db_session):
    tenant_id, patient_id, staff_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = 'revoked-' + uuid.uuid4().hex
    db_session.add(Tenant(id=tenant_id, name='revoked-' + uuid.uuid4().hex))
    db_session.flush()
    db_session.add(Patient(id=patient_id, tenant_id=tenant_id, external_id='revoked', consent_active=False))
    db_session.add(StaffUser(id=staff_id, tenant_id=tenant_id, role='clinician', token_hash=hash_staff_token(token)))
    db_session.flush()
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    db_session.execute(text('SELECT * FROM public.app_authorize_staff(:digest)'), {'digest': hash_staff_token(token)})
    from sqlalchemy.exc import ProgrammingError
    import pytest
    with pytest.raises(ProgrammingError):
        with db_session.begin_nested():
            db_session.execute(text('SELECT public.app_grant_break_glass(:id,:reason)'),
                               {'id': patient_id, 'reason': 'Emergency assessment required'})

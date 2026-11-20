"""DB-level consent regression; tests use the actual restricted runtime role."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.staff import StaffUser, CareTeamMembership
from app.services.staff_auth import hash_staff_token


def test_revoke_consent_once_and_hide_patient(db_session):
    tenant_id, patient_id, staff_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = 'consent-' + uuid.uuid4().hex
    db_session.add(Tenant(id=tenant_id, name='consent-' + uuid.uuid4().hex))
    db_session.flush()
    db_session.add(Patient(id=patient_id, tenant_id=tenant_id, external_id='consent', timezone='UTC'))
    db_session.add(StaffUser(id=staff_id, tenant_id=tenant_id, role='clinician', token_hash=hash_staff_token(token)))
    db_session.flush()
    db_session.add(CareTeamMembership(tenant_id=tenant_id, staff_id=staff_id, patient_id=patient_id))
    db_session.flush()
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    db_session.execute(text('SELECT * FROM public.app_authorize_staff(:digest)'), {'digest': hash_staff_token(token)})
    now = datetime.now(timezone.utc)
    assert db_session.execute(text('SELECT public.app_revoke_patient_consent(:patient,:now)'), {'patient': patient_id, 'now': now}).scalar_one() is True
    assert db_session.execute(text('SELECT public.app_revoke_patient_consent(:patient,:now)'), {'patient': patient_id, 'now': now}).scalar_one() is False
    assert db_session.execute(text('SELECT consent_active FROM patients WHERE id=:id'), {'id': patient_id}).scalar_one() is False
    db_session.execute(text('RESET ROLE'))
    assert db_session.execute(text("SELECT count(*) FROM audit_events WHERE patient_id=:id AND action='consent_revoked'"), {'id': patient_id}).scalar_one() == 1

"""Minimal HTTP authorization regression; no new schema or security framework."""
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.database import get_runtime_db
from app.security.staff_context import StaffIdentity, require_staff_context
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.staff import StaffUser, CareTeamMembership
from app.services.staff_auth import hash_staff_token


def test_patient_http_denies_unassigned_and_auditor(db_session):
    tenant = Tenant(id=uuid.uuid4(), name='http-authorization-' + uuid.uuid4().hex)
    db_session.add(tenant)
    db_session.flush()
    assigned = Patient(id=uuid.uuid4(), tenant_id=tenant.id, external_id='assigned')
    unassigned = Patient(id=uuid.uuid4(), tenant_id=tenant.id, external_id='unassigned')
    db_session.add_all([assigned, unassigned])
    db_session.flush()
    clinician = StaffUser(id=uuid.uuid4(), tenant_id=tenant.id, role='clinician',
                          token_hash=hash_staff_token('http-access-test'))
    db_session.add(clinician)
    db_session.flush()
    db_session.add(CareTeamMembership(tenant_id=tenant.id, staff_id=clinician.id, patient_id=assigned.id))
    db_session.flush()

    # The test database session is switched to the restricted runtime role.
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    db_session.execute(text('SELECT * FROM public.app_authorize_staff(:digest)'),
                       {'digest': hash_staff_token('http-access-test')})
    app.dependency_overrides[get_runtime_db] = lambda: db_session
    app.dependency_overrides[require_staff_context] = lambda: StaffIdentity(
        id=clinician.id, tenant_id=tenant.id, role='clinician')
    try:
        with TestClient(app) as client:
            # 404 avoids disclosing whether the unassigned patient exists.
            denied = client.get(f'/v1/patients/{unassigned.id}')
            assert denied.status_code == 404
            # Auditor role must not be able to call clinician patient endpoint.
            app.dependency_overrides[require_staff_context] = lambda: StaffIdentity(
                id=clinician.id, tenant_id=tenant.id, role='auditor')
            auditor = client.get(f'/v1/patients/{assigned.id}')
            assert auditor.status_code == 403
            # Restore clinician for positive path; endpoint records an audit event.
            app.dependency_overrides[require_staff_context] = lambda: StaffIdentity(
                id=clinician.id, tenant_id=tenant.id, role='clinician')
            allowed = client.get(f'/v1/patients/{assigned.id}')
            assert allowed.status_code == 200
            assert allowed.json()['id'] == str(assigned.id)
    finally:
        app.dependency_overrides.pop(get_runtime_db, None)
        app.dependency_overrides.pop(require_staff_context, None)

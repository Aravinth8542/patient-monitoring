"""Database-level clinician assignment and auditor isolation tests."""
import uuid
from sqlalchemy import text
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.staff import StaffUser, CareTeamMembership
from app.services.staff_auth import hash_staff_token

def test_staff_rls_care_team_and_auditor(db_session):
    tenant = Tenant(id=uuid.uuid4(), name="staff-rls-" + uuid.uuid4().hex)
    db_session.add(tenant)
    db_session.flush()
    assigned = Patient(id=uuid.uuid4(), tenant_id=tenant.id, external_id="assigned")
    unassigned = Patient(id=uuid.uuid4(), tenant_id=tenant.id, external_id="unassigned")
    db_session.add_all([assigned, unassigned])
    db_session.flush()
    clinician = StaffUser(id=uuid.uuid4(), tenant_id=tenant.id, role="clinician",
                         token_hash=hash_staff_token("staff-rls-clinician"))
    auditor = StaffUser(id=uuid.uuid4(), tenant_id=tenant.id, role="auditor",
                       token_hash=hash_staff_token("staff-rls-auditor"))
    db_session.add_all([clinician, auditor])
    db_session.flush()
    db_session.add(CareTeamMembership(tenant_id=tenant.id, staff_id=clinician.id, patient_id=assigned.id))
    db_session.flush()
    db_session.execute(text("SET LOCAL ROLE patient_monitoring_runtime"))
    db_session.execute(text("SELECT * FROM public.app_authorize_staff(:digest)"),
                       {"digest":hash_staff_token("staff-rls-clinician")})
    visible = db_session.execute(text("SELECT id FROM patients")).scalars().all()
    assert assigned.id in visible
    assert unassigned.id not in visible
    assert db_session.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 0
    db_session.execute(text("SELECT * FROM public.app_authorize_staff(:digest)"),
                       {"digest":hash_staff_token("staff-rls-auditor")})
    assert db_session.execute(text("SELECT count(*) FROM patients")).scalar_one() == 0
    assert db_session.execute(text("SELECT count(*) FROM observations")).scalar_one() == 0
    assert db_session.execute(text("SELECT public.app_staff_role()")).scalar_one() == "auditor"

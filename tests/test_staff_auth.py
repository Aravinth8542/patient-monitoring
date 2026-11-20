import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.models.tenant import Tenant
from app.models.staff import StaffUser, CareTeamMembership
from app.models.patient import Patient
from app.services.staff_auth import authenticate_staff, hash_staff_token, new_staff_token


def test_staff_authentication_and_role(db_session):
    tenant = Tenant(name="Staff Auth Test")
    db_session.add(tenant)
    db_session.flush()
    token = new_staff_token()
    user = StaffUser(tenant_id=tenant.id, role="clinician", token_hash=hash_staff_token(token))
    db_session.add(user)
    db_session.flush()
    assert authenticate_staff(db_session, f"Bearer {token}", "clinician").id == user.id
    for invalid in [None, "Bearer incorrect", "Basic wrong", "Bearer "]:
        with pytest.raises(HTTPException) as exc:
            authenticate_staff(db_session, invalid)
        assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        authenticate_staff(db_session, f"Bearer {token}", "auditor")
    assert exc.value.status_code == 403


def test_cross_tenant_membership_blocked_by_composite_fk(db_session):
    t1, t2 = Tenant(name="Clinic One"), Tenant(name="Clinic Two")
    db_session.add_all([t1, t2])
    db_session.flush()
    staff = StaffUser(tenant_id=t1.id, role="clinician", token_hash=hash_staff_token(new_staff_token()))
    patient = Patient(tenant_id=t2.id, external_id=f"test-{uuid.uuid4()}", timezone="UTC", consent_active=True)
    db_session.add_all([staff, patient])
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(CareTeamMembership(tenant_id=t1.id, staff_id=staff.id, patient_id=patient.id))
            db_session.flush()

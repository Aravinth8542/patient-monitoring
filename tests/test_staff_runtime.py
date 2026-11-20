"""Staff authentication through restricted database role, not owner ORM lookups."""
import uuid
from sqlalchemy import text
from app.models.tenant import Tenant
from app.models.staff import StaffUser
from app.services.staff_auth import hash_staff_token


def test_staff_authentication_establishes_signed_tenant_context(db_session):
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    db_session.add_all([Tenant(id=tenant_a, name='Staff auth A'), Tenant(id=tenant_b, name='Staff auth B')])
    db_session.flush()
    staff = StaffUser(tenant_id=tenant_a, role='clinician', token_hash=hash_staff_token('staff-runtime-test'))
    db_session.add(staff)
    db_session.flush()
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    assert db_session.execute(text('SELECT count(*) FROM staff_users')).scalar_one() == 0
    assert db_session.execute(text('SELECT * FROM public.app_authorize_staff(:digest)'),
        {'digest': hash_staff_token('wrong')}).first() is None
    row = db_session.execute(text('SELECT * FROM public.app_authorize_staff(:digest)'),
        {'digest': hash_staff_token('staff-runtime-test')}).one()
    assert (row.staff_id, row.tenant_id, row.staff_role) == (staff.id, tenant_a, 'clinician')
    assert db_session.execute(text('SELECT public.app_current_tenant()')).scalar_one() == tenant_a
    assert db_session.execute(text('SELECT count(*) FROM tenants')).scalar_one() == 1
    # A caller cannot replace the signed tenant context with a different tenant.
    db_session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {'tenant': str(tenant_b)})
    assert db_session.execute(text('SELECT count(*) FROM tenants')).scalar_one() == 0

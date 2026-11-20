"""Database-enforced isolation, including attempts to spoof tenant context."""
import uuid
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.models.tenant import Tenant
from app.models.patient import Patient
from app.models.device import Device
from app.services.device_auth import hash_device_token


def test_rls_filters_unscoped_queries_and_blocks_cross_tenant_writes(db_session):
    a, b = uuid.uuid4(), uuid.uuid4()
    db_session.add_all([Tenant(id=a, name='RLS A'), Tenant(id=b, name='RLS B')])
    db_session.flush()
    pa, pb = Patient(tenant_id=a, external_id=f'a-{a}'), Patient(tenant_id=b, external_id=f'b-{b}')
    db_session.add_all([pa, pb])
    db_session.flush()
    da = Device(tenant_id=a, patient_id=pa.id, token_hash=hash_device_token('rls-a-token'))
    db_session.add(da)
    db_session.flush()
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    # No authenticated context: fail closed.
    assert db_session.execute(text('SELECT count(*) FROM patients')).scalar_one() == 0
    assert db_session.execute(text('SELECT public.app_authorize_device(:id,:digest)'),
        {'id': da.id, 'digest': hash_device_token('rls-a-token')}).scalar_one() == a
    rows = db_session.execute(text('SELECT tenant_id FROM patients')).scalars().all()
    assert rows and all(row == a for row in rows)
    assert db_session.execute(text('SELECT count(*) FROM tenants')).scalar_one() == 1
    # A forged tenant ID does not match the signed context.
    db_session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {'tenant': str(b)})
    assert db_session.execute(text('SELECT count(*) FROM patients')).scalar_one() == 0
    # Reauthenticate and try inserting into the wrong tenant.
    db_session.execute(text('SELECT public.app_authorize_device(:id,:digest)'),
        {'id': da.id, 'digest': hash_device_token('rls-a-token')})
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text('INSERT INTO patients (id, tenant_id, external_id, timezone, consent_active) VALUES (:id,:tenant,:external_id,\'UTC\',true)'),
                {'id': uuid.uuid4(), 'tenant': b, 'external_id': f'cross-{uuid.uuid4()}'})

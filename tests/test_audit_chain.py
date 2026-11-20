"""HMAC chain, tenant-scoped verification, and tamper detection."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import text
from app.models.tenant import Tenant
from app.models.staff import StaffUser
from app.services.staff_auth import hash_staff_token


def test_auditor_verifies_chain_and_detects_tampering(db_session):
    tenant = Tenant(id=uuid.uuid4(), name='chain-' + uuid.uuid4().hex)
    db_session.add(tenant)
    db_session.flush()
    token = 'chain-' + uuid.uuid4().hex
    auditor = StaffUser(id=uuid.uuid4(), tenant_id=tenant.id, role='auditor',
                        token_hash=hash_staff_token(token))
    db_session.add(auditor)
    db_session.flush()
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    db_session.execute(text('SELECT * FROM public.app_authorize_staff(:digest)'),
                       {'digest': hash_staff_token(token)})
    # Runtime staff must use the authenticated, narrow audit writer.
    for action in ('audit_events_read', 'audit_chain_verified'):
        db_session.execute(text('''SELECT public.app_record_staff_audit(
            NULL, :action, :now)'''),
            {'action': action, 'now': datetime.now(timezone.utc)})
    assert db_session.execute(text('SELECT public.app_verify_audit_chain()')).scalar_one() is True
    # Simulate a privileged operator rewriting an old record. Normal runtime
    # users cannot perform this operation because of the immutable trigger.
    db_session.execute(text('RESET ROLE'))
    db_session.execute(text('ALTER TABLE audit_events DISABLE TRIGGER audit_no_update_delete'))
    db_session.execute(text('''UPDATE audit_events SET action='tampered'
      WHERE tenant_id=:tenant AND action='audit_events_read' '''), {'tenant':tenant.id})
    db_session.execute(text('ALTER TABLE audit_events ENABLE TRIGGER audit_no_update_delete'))
    db_session.execute(text('SET LOCAL ROLE patient_monitoring_runtime'))
    assert db_session.execute(text('SELECT public.app_verify_audit_chain()')).scalar_one() is False

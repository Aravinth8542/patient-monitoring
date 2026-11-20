"""Authenticate staff in PostgreSQL before establishing signed tenant context.

Revision ID: a62c5d9e301b
Revises: f92c7a6140de
"""
from alembic import op

revision = 'a62c5d9e301b'
down_revision = 'f92c7a6140de'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE FUNCTION public.app_authorize_staff(p_digest text)
    RETURNS TABLE(staff_id uuid, tenant_id uuid, staff_role text)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    DECLARE found_id uuid; found_tenant uuid; found_role text;
            secret bytea; signature text;
    BEGIN
      -- Clear any previously authenticated identity on this transaction.
      PERFORM set_config('app.tenant_id','',true);
      PERFORM set_config('app.tenant_signature','',true);
      SELECT s.id,s.tenant_id,s.role INTO found_id,found_tenant,found_role
        FROM public.staff_users s WHERE s.token_hash=p_digest;
      IF found_id IS NULL THEN RETURN; END IF;
      SELECT k.secret INTO secret FROM app_private.context_key k WHERE k.id=1;
      signature := encode(public.hmac(convert_to(
        found_tenant::text || ':' || pg_backend_pid()::text || ':' || txid_current()::text,
        'UTF8'), secret, 'sha256'),'hex');
      PERFORM set_config('app.tenant_id',found_tenant::text,true);
      PERFORM set_config('app.tenant_signature',signature,true);
      staff_id := found_id; tenant_id := found_tenant; staff_role := found_role;
      RETURN NEXT;
    END $$''')
    op.execute('REVOKE ALL ON FUNCTION public.app_authorize_staff(text) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_authorize_staff(text) TO patient_monitoring_runtime')


def downgrade():
    op.execute('DROP FUNCTION IF EXISTS public.app_authorize_staff(text)')

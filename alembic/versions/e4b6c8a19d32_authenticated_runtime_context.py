"""Signed device tenant context. Revision ID: e4b6c8a19d32; Revises: d71e3b4a9f20."""
from alembic import op
revision = 'e4b6c8a19d32'
down_revision = 'd71e3b4a9f20'
branch_labels = None
depends_on = None

TABLES = ('tenants','patients','devices','observations','ingestion_requests','staff_users','care_team_memberships')

def policies():
    for table in ('patients','devices','observations','staff_users','care_team_memberships'):
        op.execute(f'''CREATE POLICY tenant_boundary ON public.{table} TO patient_monitoring_runtime
            USING (tenant_id = public.app_current_tenant()) WITH CHECK (tenant_id = public.app_current_tenant())''')
    op.execute('''CREATE POLICY tenant_boundary ON public.tenants TO patient_monitoring_runtime
        USING (id = public.app_current_tenant()) WITH CHECK (id = public.app_current_tenant())''')
    op.execute('''CREATE POLICY tenant_boundary ON public.ingestion_requests TO patient_monitoring_runtime
        USING (EXISTS (SELECT 1 FROM public.devices d WHERE d.id=device_id AND d.tenant_id=public.app_current_tenant()))
        WITH CHECK (EXISTS (SELECT 1 FROM public.devices d WHERE d.id=device_id AND d.tenant_id=public.app_current_tenant()))''')

def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')
    op.execute('CREATE SCHEMA IF NOT EXISTS app_private')
    op.execute('REVOKE ALL ON SCHEMA app_private FROM PUBLIC')
    op.execute('CREATE TABLE app_private.context_key (id integer PRIMARY KEY, secret bytea NOT NULL)')
    op.execute('INSERT INTO app_private.context_key VALUES (1, gen_random_bytes(32))')
    op.execute('REVOKE ALL ON app_private.context_key FROM PUBLIC')
    for table in TABLES:
        op.execute(f'DROP POLICY tenant_boundary ON public.{table}')
    op.execute('DROP FUNCTION public.app_current_tenant()')
    op.execute('''CREATE FUNCTION public.app_current_tenant() RETURNS uuid
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
        DECLARE tenant_text text; signature text; expected text; secret bytea;
        BEGIN
          tenant_text := current_setting('app.tenant_id', true);
          signature := current_setting('app.tenant_signature', true);
          IF tenant_text IS NULL OR tenant_text = '' OR signature IS NULL THEN RETURN NULL; END IF;
          SELECT k.secret INTO secret FROM app_private.context_key k WHERE k.id=1;
          expected := encode(public.hmac(convert_to(tenant_text || ':' || pg_backend_pid()::text || ':' || txid_current()::text, 'UTF8'), secret, 'sha256'),'hex');
          IF signature <> expected THEN RETURN NULL; END IF;
          RETURN tenant_text::uuid;
        END $$''')
    op.execute('REVOKE ALL ON FUNCTION public.app_current_tenant() FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_current_tenant() TO patient_monitoring_runtime')
    policies()
    op.execute('''CREATE FUNCTION public.app_authorize_device(p_device uuid,p_digest text) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
        DECLARE found_tenant uuid; secret bytea; signature text;
        BEGIN
          SELECT d.tenant_id INTO found_tenant FROM public.devices d
          WHERE d.id=p_device AND d.token_hash=p_digest;
          IF found_tenant IS NULL THEN RETURN NULL; END IF;
          SELECT k.secret INTO secret FROM app_private.context_key k WHERE k.id=1;
          signature := encode(public.hmac(convert_to(found_tenant::text || ':' || pg_backend_pid()::text || ':' || txid_current()::text, 'UTF8'), secret, 'sha256'),'hex');
          PERFORM set_config('app.tenant_id',found_tenant::text,true);
          PERFORM set_config('app.tenant_signature',signature,true);
          RETURN found_tenant;
        END $$''')
    op.execute('REVOKE ALL ON FUNCTION public.app_authorize_device(uuid,text) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_authorize_device(uuid,text) TO patient_monitoring_runtime')

def downgrade():
    op.execute('DROP FUNCTION public.app_authorize_device(uuid,text)')
    for table in TABLES:
        op.execute(f'DROP POLICY tenant_boundary ON public.{table}')
    op.execute('DROP FUNCTION public.app_current_tenant()')
    op.execute('''CREATE FUNCTION public.app_current_tenant() RETURNS uuid LANGUAGE sql STABLE AS $$
        SELECT NULLIF(current_setting('app.tenant_id',true),'')::uuid $$''')
    policies()
    op.execute('DROP TABLE app_private.context_key')
    op.execute('DROP SCHEMA app_private')

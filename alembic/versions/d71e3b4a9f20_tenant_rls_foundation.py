"""Tenant row-level security policies and non-owner role foundation.

Revision ID: d71e3b4a9f20
Revises: c39d0b0b124a
"""
from alembic import op

revision = 'd71e3b4a9f20'
down_revision = 'c39d0b0b124a'
branch_labels = None
depends_on = None

TABLES = ('tenants', 'patients', 'devices', 'observations', 'ingestion_requests', 'staff_users', 'care_team_memberships')


def upgrade():
    # Migration connection must have CREATEROLE privileges; it must NOT be the application runtime role.
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'patient_monitoring_runtime') THEN
            CREATE ROLE patient_monitoring_runtime NOLOGIN NOBYPASSRLS;
        END IF;
    END $$;""")
    op.execute('GRANT USAGE ON SCHEMA public TO patient_monitoring_runtime')
    for table in TABLES:
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table} TO patient_monitoring_runtime')
        op.execute(f'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY')
    # Application context is transaction-local; absent context means no tenant rows.
    op.execute("""CREATE FUNCTION public.app_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
        $$""")
    op.execute('GRANT EXECUTE ON FUNCTION public.app_current_tenant() TO patient_monitoring_runtime')
    for table in ('patients', 'devices', 'observations', 'staff_users', 'care_team_memberships'):
        op.execute(f'''CREATE POLICY tenant_boundary ON public.{table}
            TO patient_monitoring_runtime
            USING (tenant_id = public.app_current_tenant())
            WITH CHECK (tenant_id = public.app_current_tenant())''')
    op.execute('''CREATE POLICY tenant_boundary ON public.tenants
        TO patient_monitoring_runtime
        USING (id = public.app_current_tenant())
        WITH CHECK (id = public.app_current_tenant())''')
    op.execute('''CREATE POLICY tenant_boundary ON public.ingestion_requests
        TO patient_monitoring_runtime
        USING (EXISTS (
            SELECT 1 FROM public.devices d
            WHERE d.id = device_id AND d.tenant_id = public.app_current_tenant()
        ))
        WITH CHECK (EXISTS (
            SELECT 1 FROM public.devices d
            WHERE d.id = device_id AND d.tenant_id = public.app_current_tenant()
        ))''')


def downgrade():
    for table in TABLES:
        op.execute(f'DROP POLICY IF EXISTS tenant_boundary ON public.{table}')
        op.execute(f'ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY')
    op.execute('DROP FUNCTION IF EXISTS public.app_current_tenant()')
    # Keep the role; other databases may depend on it.

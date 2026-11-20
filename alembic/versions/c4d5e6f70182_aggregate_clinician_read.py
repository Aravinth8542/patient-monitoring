"""Allow RLS-protected aggregate SELECTs by authorized clinicians."""
from alembic import op

revision = 'c4d5e6f70182'
down_revision = 'b3c4d5e6f701'
branch_labels = None
depends_on = None


def upgrade():
    for granularity in ('hourly', 'daily'):
        table = f'public.observation_{granularity}_aggregates'
        op.execute(f'''CREATE POLICY {granularity}_staff_read ON {table}
            FOR SELECT USING (
                tenant_id = public.app_current_tenant()
                AND public.app_current_staff() IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM public.patients p
                    WHERE p.id = patient_id AND p.tenant_id = tenant_id
                      AND p.consent_active AND public.app_staff_can_read(p.id)
                )
            )''')
        op.execute(f'GRANT SELECT ON {table} TO patient_monitoring_runtime')


def downgrade():
    for granularity in ('hourly', 'daily'):
        table = f'public.observation_{granularity}_aggregates'
        op.execute(f'REVOKE SELECT ON {table} FROM patient_monitoring_runtime')
        op.execute(f'DROP POLICY {granularity}_staff_read ON {table}')

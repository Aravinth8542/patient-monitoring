"""Alert episode persistence; no background processing in this revision."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='ab83e7d10429'
down_revision='a71b90c2e4d6'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('alerts',
        sa.Column('id',postgresql.UUID(as_uuid=True),primary_key=True),
        sa.Column('tenant_id',postgresql.UUID(as_uuid=True),nullable=False),
        sa.Column('patient_id',postgresql.UUID(as_uuid=True),nullable=False),
        sa.Column('rule',sa.String(40),nullable=False),
        sa.Column('severity',sa.String(20),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('episode_start',sa.DateTime(timezone=True),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['tenant_id','patient_id'],['patients.tenant_id','patients.id']),
        sa.UniqueConstraint('tenant_id','patient_id','rule','episode_start',name='uq_alert_episode'),
        sa.CheckConstraint("status IN ('open','acknowledged','resolved','retracted')",name='ck_alert_status'),
    )
    op.create_index('ix_alert_patient_rule','alerts',['tenant_id','patient_id','rule'])
    op.execute('ALTER TABLE public.alerts ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE public.alerts FORCE ROW LEVEL SECURITY')
    op.execute("""CREATE POLICY alert_tenant_staff ON public.alerts
      USING (tenant_id=public.app_current_tenant() AND
             public.app_current_staff() IS NOT NULL AND public.app_staff_assigned(patient_id))
      WITH CHECK (tenant_id=public.app_current_tenant() AND
                  public.app_current_staff() IS NOT NULL AND public.app_staff_assigned(patient_id))""")
    op.execute('GRANT SELECT ON public.alerts TO patient_monitoring_runtime')

def downgrade():
    op.execute('REVOKE SELECT ON public.alerts FROM patient_monitoring_runtime')
    op.drop_index('ix_alert_patient_rule',table_name='alerts')
    op.drop_table('alerts')

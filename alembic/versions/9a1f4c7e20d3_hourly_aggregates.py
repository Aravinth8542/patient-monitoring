"""Hourly effective-time aggregates, refreshed under restricted device context."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '9a1f4c7e20d3'
down_revision = 'e84b1c902d76'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('observation_hourly_aggregates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('bucket_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('count', sa.Integer, nullable=False),
        *[sa.Column(name, sa.Numeric(20, 4) if name.endswith(('_sum', '_avg')) else sa.Numeric(12, 4))
          for name in ('value_sum','value_min','value_max','value_avg',
                       'systolic_sum','systolic_min','systolic_max','systolic_avg',
                       'diastolic_sum','diastolic_min','diastolic_max','diastolic_avg')],
        sa.ForeignKeyConstraint(['tenant_id','patient_id'], ['patients.tenant_id','patients.id']),
        sa.UniqueConstraint('tenant_id','patient_id','type','bucket_start', name='uq_hourly_aggregate_bucket'),
    )
    op.create_index('ix_hourly_aggregate_patient_time', 'observation_hourly_aggregates',
                    ['tenant_id','patient_id','bucket_start'])
    op.execute('ALTER TABLE public.observation_hourly_aggregates ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE public.observation_hourly_aggregates FORCE ROW LEVEL SECURITY')
    # The table owner (function definer) may write only in authenticated device context.
    op.execute("""CREATE POLICY hourly_device_write ON public.observation_hourly_aggregates
        FOR ALL USING (tenant_id=public.app_current_tenant() AND public.app_current_staff() IS NULL)
        WITH CHECK (tenant_id=public.app_current_tenant() AND public.app_current_staff() IS NULL)""")
    # Runtime users cannot directly read or mutate aggregate rows.
    op.execute("""
    CREATE FUNCTION public.app_refresh_device_hourly(p_device uuid, p_client_obs_id text)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    DECLARE
      o record;
      bucket timestamptz;
    BEGIN
      SELECT id,tenant_id,patient_id,type,effective_at INTO o
      FROM public.observations
      WHERE device_id=p_device AND client_obs_id=p_client_obs_id;
      IF NOT FOUND OR public.app_current_tenant() IS DISTINCT FROM o.tenant_id
         OR public.app_current_staff() IS NOT NULL
         OR NOT EXISTS (SELECT 1 FROM public.devices d
             JOIN public.patients p ON p.id=d.patient_id AND p.tenant_id=d.tenant_id
             WHERE d.id=p_device AND d.patient_id=o.patient_id AND d.tenant_id=o.tenant_id
               AND p.consent_active)
      THEN RAISE EXCEPTION 'invalid hourly aggregate context' USING ERRCODE='42501'; END IF;

      bucket := date_trunc('hour', o.effective_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
      -- Serialize updates to the same bucket, including different devices of a patient.
      PERFORM pg_advisory_xact_lock(hashtextextended(
          o.tenant_id::text || ':' || o.patient_id::text || ':' || o.type || ':' || bucket::text, 0));

      INSERT INTO public.observation_hourly_aggregates
        (id,tenant_id,patient_id,type,bucket_start,count,
         value_sum,value_min,value_max,value_avg,
         systolic_sum,systolic_min,systolic_max,systolic_avg,
         diastolic_sum,diastolic_min,diastolic_max,diastolic_avg)
      SELECT gen_random_uuid(),o.tenant_id,o.patient_id,o.type,bucket,count(*)::integer,
         sum(value),min(value),max(value),avg(value),
         sum(systolic),min(systolic),max(systolic),avg(systolic),
         sum(diastolic),min(diastolic),max(diastolic),avg(diastolic)
      FROM public.observations
      WHERE tenant_id=o.tenant_id AND patient_id=o.patient_id AND type=o.type
        AND effective_at>=bucket AND effective_at<bucket+interval '1 hour'
      ON CONFLICT ON CONSTRAINT uq_hourly_aggregate_bucket DO UPDATE SET
        count=EXCLUDED.count,
        value_sum=EXCLUDED.value_sum,value_min=EXCLUDED.value_min,
        value_max=EXCLUDED.value_max,value_avg=EXCLUDED.value_avg,
        systolic_sum=EXCLUDED.systolic_sum,systolic_min=EXCLUDED.systolic_min,
        systolic_max=EXCLUDED.systolic_max,systolic_avg=EXCLUDED.systolic_avg,
        diastolic_sum=EXCLUDED.diastolic_sum,diastolic_min=EXCLUDED.diastolic_min,
        diastolic_max=EXCLUDED.diastolic_max,diastolic_avg=EXCLUDED.diastolic_avg;
    END $$
    """)
    op.execute('REVOKE ALL ON FUNCTION public.app_refresh_device_hourly(uuid,text) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_refresh_device_hourly(uuid,text) TO patient_monitoring_runtime')


def downgrade():
    op.execute('DROP FUNCTION public.app_refresh_device_hourly(uuid,text)')
    op.drop_index('ix_hourly_aggregate_patient_time', table_name='observation_hourly_aggregates')
    op.drop_table('observation_hourly_aggregates')

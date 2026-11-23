"""Reconcile missing-data alerts when device observations arrive.

Revision ID: b8d9e0f1a234
Revises: a7c8d9e0f112
"""
from alembic import op

revision = 'b8d9e0f1a234'
down_revision = 'a7c8d9e0f112'
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().exec_driver_sql("""
    CREATE FUNCTION public.app_reconcile_device_no_data(
        p_tenant uuid, p_patient uuid, p_now timestamptz
    ) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public AS $$
    DECLARE a record; r record; spec jsonb; cfg jsonb;
            window_interval interval; n integer := 0;
    BEGIN
      IF public.app_current_tenant() IS DISTINCT FROM p_tenant
         OR public.app_current_staff() IS NOT NULL
         OR NOT EXISTS (SELECT 1 FROM public.patients
             WHERE tenant_id=p_tenant AND id=p_patient AND consent_active)
      THEN RAISE EXCEPTION 'invalid device alert context' USING ERRCODE='42501'; END IF;

      SELECT COALESCE(alert_rules,
          '[{"id":"no_data","type":"missing_data","window_hours":24}]'::jsonb)
        INTO cfg FROM public.tenants WHERE id=p_tenant;
      FOR a IN SELECT id, rule, episode_start, created_at, status FROM public.alerts
        WHERE tenant_id=p_tenant AND patient_id=p_patient
          AND status IN ('open','acknowledged','resolved') FOR UPDATE LOOP
        SELECT value INTO spec FROM jsonb_array_elements(cfg)
          WHERE value->>'id'=a.rule AND value->>'type'='missing_data';
        IF spec IS NULL THEN CONTINUE; END IF;
        window_interval := make_interval(hours => (spec->>'window_hours')::int);
        -- A reading within the original silence window invalidates the alert.
        -- A reading after that window is genuine recovery.
        SELECT
          bool_or(effective_at > a.episode_start AND effective_at < a.episode_start + window_interval) AS backfill,
          bool_or(effective_at >= a.episode_start + window_interval) AS recovery
        INTO r FROM public.observations
        WHERE tenant_id=p_tenant AND patient_id=p_patient
          AND received_at=p_now AND effective_at > a.episode_start
          AND effective_at <= p_now;
        IF coalesce(r.backfill, false) THEN
          UPDATE public.alerts SET status='retracted', retracted_at=p_now,
            retraction_reason='late_observation_correction' WHERE id=a.id;
          n := n + 1;
        ELSIF coalesce(r.recovery, false) AND a.status <> 'resolved' THEN
          UPDATE public.alerts SET status='resolved', resolved_at=p_now WHERE id=a.id;
          n := n + 1;
        END IF;
      END LOOP;
      RETURN n;
    END $$
    """)
    op.execute('REVOKE ALL ON FUNCTION public.app_reconcile_device_no_data(uuid,uuid,timestamptz) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_reconcile_device_no_data(uuid,uuid,timestamptz) TO patient_monitoring_runtime')


def downgrade():
    op.execute('DROP FUNCTION public.app_reconcile_device_no_data(uuid,uuid,timestamptz)')

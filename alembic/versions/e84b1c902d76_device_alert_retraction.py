"""Reconcile device alert episodes with effective-time evidence."""
from alembic import op
import sqlalchemy as sa
revision = 'e84b1c902d76'
down_revision = 'cd15e6f30182'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('alerts', sa.Column('retracted_at', sa.DateTime(timezone=True)))
    op.add_column('alerts', sa.Column('retraction_reason', sa.String(100)))
    # A SECURITY DEFINER owned by the table owner is still subject to FORCE RLS.
    # Only the function owner (not the runtime role) receives UPDATE on alerts.
    op.execute("""CREATE POLICY alert_device_retract ON public.alerts FOR UPDATE
      USING (tenant_id=public.app_current_tenant() AND public.app_current_staff() IS NULL
        AND EXISTS (SELECT 1 FROM public.patients p WHERE p.tenant_id=tenant_id
                    AND p.id=patient_id AND p.consent_active))
      WITH CHECK (tenant_id=public.app_current_tenant() AND public.app_current_staff() IS NULL
        AND EXISTS (SELECT 1 FROM public.patients p WHERE p.tenant_id=tenant_id
                    AND p.id=patient_id AND p.consent_active))""")
    op.execute("""
    CREATE FUNCTION public.app_reconcile_device_alerts(p_tenant uuid, p_patient uuid, p_now timestamptz)
    RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    DECLARE
      r record; a record;
      low_start timestamptz; low_last timestamptz; low_count integer := 0;
      hr_prev record; hr_active boolean := false; hr_trigger boolean; hr_found boolean;
      valid_spo2 timestamptz[] := ARRAY[]::timestamptz[];
      valid_hr timestamptz[] := ARRAY[]::timestamptz[];
      n integer := 0;
    BEGIN
      IF public.app_current_tenant() IS DISTINCT FROM p_tenant
         OR public.app_current_staff() IS NOT NULL
         OR NOT EXISTS (SELECT 1 FROM public.patients
              WHERE tenant_id=p_tenant AND id=p_patient AND consent_active)
      THEN RAISE EXCEPTION 'invalid device alert context' USING ERRCODE='42501'; END IF;

      FOR r IN SELECT effective_at, value FROM public.observations
        WHERE tenant_id=p_tenant AND patient_id=p_patient AND type='spo2'
          AND value IS NOT NULL AND effective_at <= p_now
        ORDER BY effective_at, id LOOP
        IF r.value >= 92 OR (low_last IS NOT NULL AND r.effective_at-low_last > interval '10 minutes') THEN
          low_start := NULL; low_last := NULL; low_count := 0;
        END IF;
        IF r.value < 92 THEN
          IF low_count = 0 THEN low_start := r.effective_at; END IF;
          low_last := r.effective_at; low_count := low_count+1;
          IF low_count >= 3 AND r.effective_at-low_start >= interval '10 minutes'
             AND NOT (low_start = ANY(valid_spo2)) THEN
            valid_spo2 := array_append(valid_spo2,low_start);
          END IF;
        END IF;
      END LOOP;

      FOR r IN SELECT id,effective_at,value FROM public.observations
        WHERE tenant_id=p_tenant AND patient_id=p_patient AND type='heart_rate'
          AND value IS NOT NULL AND effective_at <= p_now
        ORDER BY effective_at, id LOOP
        SELECT o.effective_at,o.value INTO hr_prev FROM public.observations o
          WHERE o.tenant_id=p_tenant AND o.patient_id=p_patient AND o.type='heart_rate'
            AND o.value IS NOT NULL AND o.effective_at < r.effective_at
            AND o.effective_at >= r.effective_at-interval '15 minutes'
          ORDER BY o.value ASC, o.effective_at ASC LIMIT 1;
        hr_found := FOUND;
        IF hr_found THEN
          hr_trigger := r.value-hr_prev.value >= 30;
        ELSE
          hr_trigger := false;
        END IF;
        IF hr_trigger AND NOT hr_active AND NOT (hr_prev.effective_at = ANY(valid_hr)) THEN
          valid_hr := array_append(valid_hr,hr_prev.effective_at);
        END IF;
        hr_active := hr_trigger;
      END LOOP;

      FOR a IN SELECT id,rule,episode_start FROM public.alerts
        WHERE tenant_id=p_tenant AND patient_id=p_patient
          AND rule IN ('low_spo2','hr_rise') AND status IN ('open','acknowledged','resolved')
          AND episode_start <= p_now FOR UPDATE LOOP
        IF (a.rule='low_spo2' AND NOT (a.episode_start = ANY(valid_spo2)))
           OR (a.rule='hr_rise' AND NOT (a.episode_start = ANY(valid_hr))) THEN
          UPDATE public.alerts SET status='retracted',retracted_at=p_now,
            retraction_reason='late_observation_correction' WHERE id=a.id;
          n := n+1;
        END IF;
      END LOOP;
      RETURN n;
    END $$
    """)
    op.execute('REVOKE ALL ON FUNCTION public.app_reconcile_device_alerts(uuid,uuid,timestamptz) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_reconcile_device_alerts(uuid,uuid,timestamptz) TO patient_monitoring_runtime')

def downgrade():
    op.execute('DROP FUNCTION public.app_reconcile_device_alerts(uuid,uuid,timestamptz)')
    op.execute('DROP POLICY alert_device_retract ON public.alerts')
    op.drop_column('alerts','retraction_reason')
    op.drop_column('alerts','retracted_at')

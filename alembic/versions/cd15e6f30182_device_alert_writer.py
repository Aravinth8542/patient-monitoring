"""Restricted alert insertion for device ingestion, without exposing alert history."""
from alembic import op
revision = 'cd15e6f30182'
down_revision = 'bc94f1e23071'
branch_labels = None
depends_on = None

def upgrade():
    # FORCE RLS also applies to SECURITY DEFINER table owners.
    # Runtime devices still have no direct INSERT privilege on alerts.
    op.execute("""CREATE POLICY alert_device_insert ON public.alerts FOR INSERT
        WITH CHECK (tenant_id=public.app_current_tenant()
          AND public.app_current_staff() IS NULL
          AND EXISTS (SELECT 1 FROM public.patients p
            WHERE p.id=patient_id AND p.tenant_id=tenant_id AND p.consent_active))""")
    op.execute("""
    CREATE FUNCTION public.app_insert_device_alert(
        p_tenant uuid, p_patient uuid, p_rule text, p_severity text,
        p_start timestamptz, p_now timestamptz
    ) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog,public AS $$
    DECLARE inserted_count integer;
    BEGIN
      IF public.app_current_tenant() IS DISTINCT FROM p_tenant
         OR public.app_current_staff() IS NOT NULL
         OR NOT EXISTS (SELECT 1 FROM public.patients
             WHERE tenant_id=p_tenant AND id=p_patient AND consent_active)
         OR (p_rule,p_severity) NOT IN (('low_spo2','high'),('hr_rise','medium'))
         OR p_start > p_now
      THEN RAISE EXCEPTION 'invalid device alert context' USING ERRCODE='42501'; END IF;
      INSERT INTO public.alerts(id,tenant_id,patient_id,rule,severity,status,episode_start,created_at)
      VALUES(gen_random_uuid(),p_tenant,p_patient,p_rule,p_severity,'open',p_start,p_now)
      ON CONFLICT ON CONSTRAINT uq_alert_episode DO NOTHING;
      GET DIAGNOSTICS inserted_count = ROW_COUNT;
      RETURN inserted_count = 1;
    END $$
    """)
    op.execute('REVOKE ALL ON FUNCTION public.app_insert_device_alert(uuid,uuid,text,text,timestamptz,timestamptz) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_insert_device_alert(uuid,uuid,text,text,timestamptz,timestamptz) TO patient_monitoring_runtime')

def downgrade():
    op.execute('DROP POLICY alert_device_insert ON public.alerts')
    op.execute('DROP FUNCTION public.app_insert_device_alert(uuid,uuid,text,text,timestamptz,timestamptz)')

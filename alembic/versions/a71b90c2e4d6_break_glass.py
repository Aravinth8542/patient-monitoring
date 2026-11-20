"""Short-lived, audited emergency clinician access.

Revision ID: a71b90c2e4d6
Revises: f17a6d3c0e92
"""
from alembic import op
revision = 'a71b90c2e4d6'
down_revision = 'f17a6d3c0e92'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
    CREATE TABLE public.break_glass_grants (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES public.tenants(id),
      staff_id uuid NOT NULL,
      patient_id uuid NOT NULL,
      reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 10 AND 500),
      granted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      expires_at timestamptz NOT NULL,
      FOREIGN KEY (tenant_id,staff_id) REFERENCES public.staff_users(tenant_id,id),
      FOREIGN KEY (tenant_id,patient_id) REFERENCES public.patients(tenant_id,id)
    )
    """)
    op.execute("CREATE INDEX ix_break_glass_active ON public.break_glass_grants (tenant_id,staff_id,patient_id,expires_at)")
    op.execute("REVOKE ALL ON public.break_glass_grants FROM PUBLIC, patient_monitoring_runtime")
    op.execute("""
    CREATE FUNCTION public.app_staff_can_read(p_patient uuid) RETURNS boolean
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    DECLARE t uuid; s uuid;
    BEGIN
      t := public.app_current_tenant(); s := public.app_current_staff();
      IF t IS NULL OR s IS NULL OR public.app_staff_role() IS DISTINCT FROM 'clinician' THEN RETURN false; END IF;
      IF public.app_staff_assigned(p_patient) THEN RETURN true; END IF;
      IF NOT EXISTS (SELECT 1 FROM public.patients p WHERE p.id=p_patient AND p.tenant_id=t AND p.consent_active) THEN RETURN false; END IF;
      RETURN EXISTS (
        SELECT 1 FROM public.break_glass_grants g
        WHERE g.tenant_id=t AND g.staff_id=s AND g.patient_id=p_patient
          AND g.expires_at > clock_timestamp()
      );
    END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.app_staff_can_read(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.app_staff_can_read(uuid) TO patient_monitoring_runtime")
    op.execute("""
    CREATE FUNCTION public.app_grant_break_glass(p_patient uuid,p_reason text)
    RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    DECLARE t uuid; s uuid; expiry timestamptz;
    BEGIN
      t := public.app_current_tenant(); s := public.app_current_staff();
      IF t IS NULL OR s IS NULL OR public.app_staff_role() IS DISTINCT FROM 'clinician'
         OR p_reason IS NULL OR length(btrim(p_reason)) NOT BETWEEN 10 AND 500
         OR NOT EXISTS (SELECT 1 FROM public.patients p WHERE p.id=p_patient AND p.tenant_id=t AND p.consent_active)
      THEN RAISE EXCEPTION 'emergency access denied' USING ERRCODE='42501'; END IF;
      expiry := clock_timestamp() + interval '15 minutes';
      INSERT INTO public.break_glass_grants(tenant_id,staff_id,patient_id,reason,expires_at)
      VALUES (t,s,p_patient,btrim(p_reason),expiry);
      INSERT INTO public.audit_events(tenant_id,actor_id,patient_id,action,occurred_at,reason)
      VALUES (t,s,p_patient,'break_glass_granted',clock_timestamp(),btrim(p_reason));
      RETURN expiry;
    END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.app_grant_break_glass(uuid,text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.app_grant_break_glass(uuid,text) TO patient_monitoring_runtime")
    op.execute("""
    CREATE FUNCTION public.app_record_emergency_read(p_patient uuid,p_at timestamptz)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    DECLARE t uuid; s uuid;
    BEGIN
      t := public.app_current_tenant(); s := public.app_current_staff();
      IF NOT public.app_staff_can_read(p_patient) THEN RAISE EXCEPTION 'access denied' USING ERRCODE='42501'; END IF;
      INSERT INTO public.audit_events(tenant_id,actor_id,patient_id,action,occurred_at)
      VALUES (t,s,p_patient,'patient_emergency_read',p_at);
    END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.app_record_emergency_read(uuid,timestamptz) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.app_record_emergency_read(uuid,timestamptz) TO patient_monitoring_runtime")
    # Signed staff context is required. Device contexts retain their existing ingestion policy.
    op.execute("DROP POLICY tenant_boundary ON public.patients")
    op.execute("""CREATE POLICY tenant_boundary ON public.patients TO patient_monitoring_runtime
      USING (tenant_id=public.app_current_tenant() AND
        (public.app_current_staff() IS NULL OR public.app_staff_can_read(id)))
      WITH CHECK (tenant_id=public.app_current_tenant())""")
    op.execute("DROP POLICY tenant_boundary ON public.observations")
    op.execute("""CREATE POLICY tenant_boundary ON public.observations TO patient_monitoring_runtime
      USING (tenant_id=public.app_current_tenant() AND
        (public.app_current_staff() IS NULL OR public.app_staff_can_read(patient_id)))
      WITH CHECK (tenant_id=public.app_current_tenant())""")

def downgrade():
    raise RuntimeError('Emergency access security downgrade requires review')

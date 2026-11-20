"""Enforce care-team and auditor read restrictions within PostgreSQL RLS.

Revision ID: d95e2c7b041a
Revises: c84f0e91a2bd
"""
from alembic import op

revision = "d95e2c7b041a"
down_revision = "c84f0e91a2bd"
branch_labels = None
depends_on = None

def upgrade():
    # SECURITY DEFINER avoids recursive RLS when checking staff/membership.
    # The signed app_current_staff() identity cannot be set by arbitrary SQL.
    op.execute("""
    CREATE FUNCTION public.app_staff_role() RETURNS text
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    DECLARE actor uuid; tenant uuid; result text;
    BEGIN
      actor := public.app_current_staff();
      tenant := public.app_current_tenant();
      IF actor IS NULL OR tenant IS NULL THEN RETURN NULL; END IF;
      SELECT s.role INTO result FROM public.staff_users s
        WHERE s.id=actor AND s.tenant_id=tenant;
      RETURN result;
    END $$""")
    op.execute("REVOKE ALL ON FUNCTION public.app_staff_role() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.app_staff_role() TO patient_monitoring_runtime")
    op.execute("""
    CREATE FUNCTION public.app_staff_assigned(p_patient uuid) RETURNS boolean
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    DECLARE actor uuid; tenant uuid;
    BEGIN
      actor := public.app_current_staff();
      tenant := public.app_current_tenant();
      IF actor IS NULL OR tenant IS NULL THEN RETURN false; END IF;
      RETURN EXISTS (
        SELECT 1 FROM public.care_team_memberships c
        JOIN public.staff_users s ON s.id=c.staff_id AND s.tenant_id=c.tenant_id
        WHERE c.patient_id=p_patient AND c.tenant_id=tenant
          AND c.staff_id=actor AND s.role='clinician'
      );
    END $$""")
    op.execute("REVOKE ALL ON FUNCTION public.app_staff_assigned(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.app_staff_assigned(uuid) TO patient_monitoring_runtime")
    # Keep device ingestion operational: device context has no signed staff identity.
    # This is an intermediate policy; device-scoped identity remains to be enforced.
    for table in ("patients", "observations"):
        op.execute(f"DROP POLICY tenant_boundary ON public.{table}")
    op.execute("""
    CREATE POLICY tenant_boundary ON public.patients TO patient_monitoring_runtime
      USING (tenant_id=public.app_current_tenant() AND
        (public.app_current_staff() IS NULL OR public.app_staff_assigned(id)))
      WITH CHECK (tenant_id=public.app_current_tenant())""")
    op.execute("""
    CREATE POLICY tenant_boundary ON public.observations TO patient_monitoring_runtime
      USING (tenant_id=public.app_current_tenant() AND
        (public.app_current_staff() IS NULL OR public.app_staff_assigned(patient_id)))
      WITH CHECK (tenant_id=public.app_current_tenant())""")
    # Audit rows: auditors can inspect metadata, clinicians cannot query audit history.
    op.execute("DROP POLICY audit_tenant ON public.audit_events")
    op.execute("""
    CREATE POLICY audit_tenant ON public.audit_events TO patient_monitoring_runtime
      USING (tenant_id=public.app_current_tenant() AND public.app_staff_role()='auditor')
      WITH CHECK (tenant_id=public.app_current_tenant()
        AND actor_id=public.app_current_staff())""")

def downgrade():
    raise RuntimeError("Security policy downgrade requires explicit review")

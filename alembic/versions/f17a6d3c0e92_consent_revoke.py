"""Atomic clinician-authorized consent revocation with audit event.

Revision ID: f17a6d3c0e92
Revises: e06a13c9b742
"""
from alembic import op

revision = 'f17a6d3c0e92'
down_revision = 'e06a13c9b742'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION public.app_revoke_patient_consent(p_patient uuid, p_at timestamptz)
    RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
    SET search_path=pg_catalog,public AS $$
    DECLARE v_tenant uuid; v_actor uuid; v_updated integer;
    BEGIN
      v_tenant := public.app_current_tenant();
      v_actor := public.app_current_staff();
      IF v_tenant IS NULL OR v_actor IS NULL
         OR public.app_staff_role() IS DISTINCT FROM 'clinician'
         OR NOT public.app_staff_assigned(p_patient) THEN
        RAISE EXCEPTION 'clinician care-team authorization required' USING ERRCODE='42501';
      END IF;
      UPDATE public.patients
         SET consent_active=false
       WHERE id=p_patient AND tenant_id=v_tenant AND consent_active=true;
      GET DIAGNOSTICS v_updated = ROW_COUNT;
      IF v_updated > 0 THEN
        INSERT INTO public.audit_events (tenant_id,actor_id,patient_id,action,occurred_at)
        VALUES (v_tenant,v_actor,p_patient,'consent_revoked',p_at);
      END IF;
      RETURN v_updated > 0;
    END $$
    """)
    op.execute('REVOKE ALL ON FUNCTION public.app_revoke_patient_consent(uuid,timestamptz) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_revoke_patient_consent(uuid,timestamptz) TO patient_monitoring_runtime')


def downgrade():
    op.execute('DROP FUNCTION public.app_revoke_patient_consent(uuid,timestamptz)')

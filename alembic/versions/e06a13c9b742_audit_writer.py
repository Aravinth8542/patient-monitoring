"""Allow audited writes without granting clinicians audit-history SELECT.

Revision ID: e06a13c9b742
Revises: d95e2c7b041a
"""
from alembic import op
revision = "e06a13c9b742"
down_revision = "d95e2c7b041a"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
    CREATE FUNCTION public.app_record_staff_audit(
        p_patient uuid, p_action text, p_occurred_at timestamptz,
        p_reason text DEFAULT NULL
    ) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    DECLARE v_tenant uuid; v_actor uuid; v_id uuid;
    BEGIN
        v_tenant := public.app_current_tenant();
        v_actor := public.app_current_staff();
        IF v_tenant IS NULL OR v_actor IS NULL THEN
            RAISE EXCEPTION 'authenticated staff context required';
        END IF;
        IF p_action NOT IN ('patient_metadata_read', 'audit_events_read', 'audit_chain_verified') THEN
            RAISE EXCEPTION 'unsupported audit action';
        END IF;
        IF (p_action='patient_metadata_read') THEN
            IF p_patient IS NULL OR NOT public.app_staff_assigned(p_patient) THEN
                RAISE EXCEPTION 'patient assignment required';
            END IF;
        ELSE
            IF p_patient IS NOT NULL OR public.app_staff_role() IS DISTINCT FROM 'auditor' THEN
                RAISE EXCEPTION 'auditor required';
            END IF;
        END IF;
        INSERT INTO public.audit_events
          (tenant_id,actor_id,patient_id,action,occurred_at,reason)
        VALUES (v_tenant,v_actor,p_patient,p_action,p_occurred_at,p_reason)
        RETURNING id INTO v_id;
        RETURN v_id;
    END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.app_record_staff_audit(uuid,text,timestamptz,text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.app_record_staff_audit(uuid,text,timestamptz,text) TO patient_monitoring_runtime")
    # All runtime audit writes must use the narrow, authenticated function.
    op.execute("REVOKE INSERT ON public.audit_events FROM patient_monitoring_runtime")

def downgrade():
    raise RuntimeError('Audit writer downgrade requires explicit security review')

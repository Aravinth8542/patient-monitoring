
"""Audit successful patient alert-list reads.

Revision ID: c9e0f1a2b345
Revises: b8d9e0f1a234
"""
from alembic import op

revision = "c9e0f1a2b345"
down_revision = "b8d9e0f1a234"
branch_labels = None
depends_on = None


def _replace_audit_function(allow_alert_reads: bool):
    actions = [
        "patient_metadata_read",
        "patient_aggregates_read",
        "audit_events_read",
        "audit_chain_verified",
    ]
    patient_actions = [
        "patient_metadata_read",
        "patient_aggregates_read",
    ]

    if allow_alert_reads:
        actions.append("patient_alerts_read")
        patient_actions.append("patient_alerts_read")

    allowed = ", ".join(f"'{action}'" for action in actions)
    patient_allowed = ", ".join(f"'{action}'" for action in patient_actions)

    op.execute(f"""
    CREATE OR REPLACE FUNCTION public.app_record_staff_audit(
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

        IF p_action NOT IN ({allowed}) THEN
            RAISE EXCEPTION 'unsupported audit action';
        END IF;

        IF p_action IN ({patient_allowed}) THEN
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


def upgrade():
    _replace_audit_function(allow_alert_reads=True)


def downgrade():
    _replace_audit_function(allow_alert_reads=False)

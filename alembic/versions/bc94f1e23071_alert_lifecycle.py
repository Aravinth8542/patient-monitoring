"""Minimal clinician alert lifecycle with audited transitions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='bc94f1e23071'
down_revision='ab83e7d10429'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('alerts', sa.Column('acknowledged_at', sa.DateTime(timezone=True)))
    op.add_column('alerts', sa.Column('acknowledged_by', postgresql.UUID(as_uuid=True)))
    op.add_column('alerts', sa.Column('resolved_at', sa.DateTime(timezone=True)))
    op.add_column('alerts', sa.Column('resolved_by', postgresql.UUID(as_uuid=True)))
    op.execute('DROP POLICY alert_tenant_staff ON public.alerts')
    op.execute("""CREATE POLICY alert_tenant_staff ON public.alerts
      USING (tenant_id=public.app_current_tenant() AND
             public.app_current_staff() IS NOT NULL AND public.app_staff_can_read(patient_id))
      WITH CHECK (tenant_id=public.app_current_tenant() AND
                  public.app_current_staff() IS NOT NULL AND public.app_staff_can_read(patient_id))""")
    op.execute("""
    CREATE FUNCTION public.app_transition_alert(p_alert uuid,p_action text,p_now timestamptz)
    RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    DECLARE v_tenant uuid; v_staff uuid; v_patient uuid; v_status text;
    BEGIN
      v_tenant:=public.app_current_tenant(); v_staff:=public.app_current_staff();
      IF v_tenant IS NULL OR v_staff IS NULL OR public.app_staff_role() IS DISTINCT FROM 'clinician'
        THEN RAISE EXCEPTION 'clinician required' USING ERRCODE='42501'; END IF;
      IF p_action NOT IN ('acknowledge','resolve') THEN RAISE EXCEPTION 'invalid action' USING ERRCODE='22023'; END IF;
      SELECT a.patient_id,a.status INTO v_patient,v_status FROM public.alerts a
        JOIN public.patients p ON p.id=a.patient_id AND p.tenant_id=a.tenant_id
        WHERE a.id=p_alert AND a.tenant_id=v_tenant AND p.consent_active
        FOR UPDATE OF a;
      IF v_patient IS NULL OR NOT public.app_staff_can_read(v_patient)
        THEN RAISE EXCEPTION 'alert not found' USING ERRCODE='42501'; END IF;
      IF p_action='acknowledge' AND v_status='open' THEN
        UPDATE public.alerts SET status='acknowledged',acknowledged_at=p_now,acknowledged_by=v_staff WHERE id=p_alert;
        v_status:='acknowledged';
      ELSIF p_action='resolve' AND v_status='acknowledged' THEN
        UPDATE public.alerts SET status='resolved',resolved_at=p_now,resolved_by=v_staff WHERE id=p_alert;
        v_status:='resolved';
      ELSE
        RAISE EXCEPTION 'invalid alert transition' USING ERRCODE='22023';
      END IF;
      INSERT INTO public.audit_events(tenant_id,actor_id,patient_id,action,occurred_at)
        VALUES(v_tenant,v_staff,v_patient,'alert_'||p_action,p_now);
      RETURN v_status;
    END $$
    """)
    op.execute('REVOKE ALL ON FUNCTION public.app_transition_alert(uuid,text,timestamptz) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_transition_alert(uuid,text,timestamptz) TO patient_monitoring_runtime')

def downgrade():
    op.execute('DROP FUNCTION public.app_transition_alert(uuid,text,timestamptz)')
    op.execute('DROP POLICY alert_tenant_staff ON public.alerts')
    op.execute("""CREATE POLICY alert_tenant_staff ON public.alerts
      USING (tenant_id=public.app_current_tenant() AND public.app_current_staff() IS NOT NULL AND public.app_staff_assigned(patient_id))
      WITH CHECK (tenant_id=public.app_current_tenant() AND public.app_current_staff() IS NOT NULL AND public.app_staff_assigned(patient_id))""")
    op.drop_column('alerts','resolved_by')
    op.drop_column('alerts','resolved_at')
    op.drop_column('alerts','acknowledged_by')
    op.drop_column('alerts','acknowledged_at')

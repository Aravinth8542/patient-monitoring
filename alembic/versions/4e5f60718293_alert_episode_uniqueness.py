"""Allow historical invalid alert keys to be reused."""
from alembic import op
import sqlalchemy as sa

revision = '4e5f60718293'
down_revision = '3d4e5f607182'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('uq_alert_episode', 'alerts', type_='unique')
    op.create_index('uq_alert_episode', 'alerts', ['tenant_id','patient_id','rule','episode_start'], unique=True,
                    postgresql_where=sa.text("status IN ('open','acknowledged','resolved')"))
    op.execute("CREATE OR REPLACE FUNCTION public.app_insert_device_alert(\n  p_tenant uuid, p_patient uuid, p_rule text, p_severity text,\n  p_start timestamptz, p_now timestamptz\n) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $function$\nDECLARE inserted_count integer;\nBEGIN\n  IF p_start > p_now OR NOT EXISTS (\n    SELECT 1 FROM public.app_valid_device_alerts(p_tenant,p_patient,p_now) v\n    WHERE v.rule=p_rule AND v.severity=p_severity AND v.episode_start=p_start)\n  THEN RAISE EXCEPTION 'invalid device alert context' USING ERRCODE='42501'; END IF;\n  INSERT INTO public.alerts(id,tenant_id,patient_id,rule,severity,status,episode_start,created_at)\n  VALUES(gen_random_uuid(),p_tenant,p_patient,p_rule,p_severity,'open',p_start,p_now)\n  ON CONFLICT (tenant_id,patient_id,rule,episode_start) WHERE status IN ('open','acknowledged','resolved') DO NOTHING;\n  GET DIAGNOSTICS inserted_count = ROW_COUNT;\n  RETURN inserted_count = 1;\nEND $function$")


def downgrade():
    # Fails transactionally if historical keys have been reused; never delete history.
    op.drop_index('uq_alert_episode', table_name='alerts')
    op.create_unique_constraint('uq_alert_episode', 'alerts', ['tenant_id','patient_id','rule','episode_start'])
    op.execute("CREATE OR REPLACE FUNCTION public.app_insert_device_alert(\n  p_tenant uuid, p_patient uuid, p_rule text, p_severity text,\n  p_start timestamptz, p_now timestamptz\n) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $function$\nDECLARE inserted_count integer;\nBEGIN\n  IF p_start > p_now OR NOT EXISTS (\n    SELECT 1 FROM public.app_valid_device_alerts(p_tenant,p_patient,p_now) v\n    WHERE v.rule=p_rule AND v.severity=p_severity AND v.episode_start=p_start)\n  THEN RAISE EXCEPTION 'invalid device alert context' USING ERRCODE='42501'; END IF;\n  INSERT INTO public.alerts(id,tenant_id,patient_id,rule,severity,status,episode_start,created_at)\n  VALUES(gen_random_uuid(),p_tenant,p_patient,p_rule,p_severity,'open',p_start,p_now)\n  ON CONFLICT ON CONSTRAINT uq_alert_episode DO NOTHING;\n  GET DIAGNOSTICS inserted_count = ROW_COUNT;\n  RETURN inserted_count = 1;\nEND $function$")

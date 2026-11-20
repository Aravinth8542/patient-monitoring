"""Audited care-team reads; signed staff identity.

Revision ID: b73d2a90f641
Revises: a62c5d9e301b
"""
from alembic import op

revision = "b73d2a90f641"
down_revision = "a62c5d9e301b"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""CREATE TABLE public.audit_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES public.tenants(id),
        actor_id uuid NOT NULL,
        patient_id uuid,
        action text NOT NULL,
        occurred_at timestamptz NOT NULL,
        reason text,
        CONSTRAINT audit_action_nonempty CHECK (length(action) > 0)
    )""")
    op.execute("ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT ON public.audit_events TO patient_monitoring_runtime")
    op.execute("""CREATE POLICY audit_tenant ON public.audit_events TO patient_monitoring_runtime
        USING (tenant_id = public.app_current_tenant())
        WITH CHECK (tenant_id = public.app_current_tenant())""")
    op.execute("""CREATE FUNCTION public.app_audit_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'audit_events are append-only';
        END $$""")
    op.execute("""CREATE TRIGGER audit_no_update_delete BEFORE UPDATE OR DELETE
        ON public.audit_events FOR EACH ROW EXECUTE FUNCTION public.app_audit_immutable()""")
    # Only a successful staff authentication may establish the staff identity.
    op.execute("""CREATE FUNCTION public.app_current_staff() RETURNS uuid
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
        DECLARE staff_text text; sig text; expected text; secret bytea;
        BEGIN
          IF public.app_current_tenant() IS NULL THEN RETURN NULL; END IF;
          staff_text := current_setting('app.staff_id',true);
          sig := current_setting('app.staff_signature',true);
          IF staff_text IS NULL OR staff_text='' OR sig IS NULL OR sig='' THEN RETURN NULL; END IF;
          SELECT k.secret INTO secret FROM app_private.context_key k WHERE k.id=1;
          expected := encode(public.hmac(convert_to(
            staff_text || ':' || public.app_current_tenant()::text || ':' ||
            pg_backend_pid()::text || ':' || txid_current()::text, 'UTF8'),
            secret, 'sha256'),'hex');
          IF sig <> expected THEN RETURN NULL; END IF;
          RETURN staff_text::uuid;
        END $$""")
    op.execute('REVOKE ALL ON FUNCTION public.app_current_staff() FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_current_staff() TO patient_monitoring_runtime')
    op.execute('DROP FUNCTION public.app_authorize_staff(text)')
    op.execute("""CREATE FUNCTION public.app_authorize_staff(p_digest text)
    RETURNS TABLE(staff_id uuid, tenant_id uuid, staff_role text)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    DECLARE found_id uuid; found_tenant uuid; found_role text;
            secret bytea; signature text; staff_signature text;
    BEGIN
      PERFORM set_config('app.tenant_id','',true);
      PERFORM set_config('app.tenant_signature','',true);
      PERFORM set_config('app.staff_id','',true);
      PERFORM set_config('app.staff_signature','',true);
      SELECT s.id,s.tenant_id,s.role INTO found_id,found_tenant,found_role
        FROM public.staff_users s WHERE s.token_hash=p_digest;
      IF found_id IS NULL THEN RETURN; END IF;
      SELECT k.secret INTO secret FROM app_private.context_key k WHERE k.id=1;
      signature := encode(public.hmac(convert_to(
        found_tenant::text || ':' || pg_backend_pid()::text || ':' || txid_current()::text,
        'UTF8'), secret, 'sha256'),'hex');
      staff_signature := encode(public.hmac(convert_to(
        found_id::text || ':' || found_tenant::text || ':' ||
        pg_backend_pid()::text || ':' || txid_current()::text,
        'UTF8'), secret, 'sha256'),'hex');
      PERFORM set_config('app.tenant_id',found_tenant::text,true);
      PERFORM set_config('app.tenant_signature',signature,true);
      PERFORM set_config('app.staff_id',found_id::text,true);
      PERFORM set_config('app.staff_signature',staff_signature,true);
      staff_id := found_id; tenant_id := found_tenant; staff_role := found_role;
      RETURN NEXT;
    END $$""")
    op.execute('REVOKE ALL ON FUNCTION public.app_authorize_staff(text) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_authorize_staff(text) TO patient_monitoring_runtime')
    # Audit writes must be tied to the authenticated staff identity.
    op.execute("""CREATE FUNCTION public.app_audit_staff_insert_guard() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF public.app_current_staff() IS NULL OR
           NEW.actor_id <> public.app_current_staff() OR
           NEW.tenant_id <> public.app_current_tenant() THEN
          RAISE EXCEPTION 'invalid audit actor';
        END IF;
        RETURN NEW;
      END $$""")
    op.execute("""CREATE TRIGGER audit_actor_guard BEFORE INSERT ON public.audit_events
        FOR EACH ROW EXECUTE FUNCTION public.app_audit_staff_insert_guard()""")

def downgrade():
    # Intentionally fail closed rather than silently removing an audit history table.
    raise RuntimeError('Audit migration downgrade requires a reviewed data-retention plan')

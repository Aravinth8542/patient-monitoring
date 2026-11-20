"""Per-tenant HMAC audit hash chain and verification.

Revision ID: c84f0e91a2bd
Revises: b73d2a90f641
"""
from alembic import op

revision = "c84f0e91a2bd"
down_revision = "b73d2a90f641"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE public.audit_events ADD COLUMN previous_hash text")
    op.execute("ALTER TABLE public.audit_events ADD COLUMN event_hash text")
    # Serialize inserts per tenant; stable ordering is required for a verifiable chain.
    op.execute("""CREATE FUNCTION public.app_audit_hash_insert() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE prior text; secret bytea; payload text;
      BEGIN
        PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text, 77291));
        SELECT a.event_hash INTO prior FROM public.audit_events a
          WHERE a.tenant_id=NEW.tenant_id ORDER BY a.chain_sequence DESC LIMIT 1;
        NEW.previous_hash := COALESCE(prior, repeat('0',64));
        SELECT k.secret INTO secret FROM app_private.context_key k WHERE k.id=1;
        payload := concat_ws('|', NEW.previous_hash, NEW.id::text,
          NEW.tenant_id::text, NEW.actor_id::text, COALESCE(NEW.patient_id::text,''),
          NEW.action, to_char(NEW.occurred_at AT TIME ZONE 'UTC',
          'YYYY-MM-DD"T"HH24:MI:SS.US'), COALESCE(NEW.reason,''));
        NEW.event_hash := encode(public.hmac(convert_to(payload,'UTF8'),secret,'sha256'),'hex');
        RETURN NEW;
      END $$""")
    # Monotonic global sequence supplies deterministic ordering, including tied timestamps.
    op.execute("ALTER TABLE public.audit_events ADD COLUMN chain_sequence bigint GENERATED ALWAYS AS IDENTITY")
    op.execute("CREATE UNIQUE INDEX uq_audit_chain_sequence ON public.audit_events(chain_sequence)")
    # Existing events require backfill in chain order. The old immutability trigger is
    # temporarily disabled only inside this atomic migration transaction.
    op.execute("ALTER TABLE public.audit_events DISABLE TRIGGER audit_no_update_delete")
    op.execute("""DO $$ DECLARE r record; prior text; secret bytea; payload text; digest text;
      BEGIN
        SELECT k.secret INTO secret FROM app_private.context_key k WHERE k.id=1;
        FOR r IN SELECT * FROM public.audit_events ORDER BY tenant_id,chain_sequence LOOP
          SELECT a.event_hash INTO prior FROM public.audit_events a
            WHERE a.tenant_id=r.tenant_id AND a.chain_sequence<r.chain_sequence
              ORDER BY a.chain_sequence DESC LIMIT 1;
          prior := COALESCE(prior,repeat('0',64));
          payload := concat_ws('|',prior,r.id::text,r.tenant_id::text,r.actor_id::text,
            COALESCE(r.patient_id::text,''),r.action,
            to_char(r.occurred_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US'),
            COALESCE(r.reason,''));
          digest := encode(public.hmac(convert_to(payload,'UTF8'),secret,'sha256'),'hex');
          UPDATE public.audit_events SET previous_hash=prior,event_hash=digest WHERE id=r.id;
        END LOOP;
      END $$""")
    op.execute("ALTER TABLE public.audit_events ENABLE TRIGGER audit_no_update_delete")
    op.execute("ALTER TABLE public.audit_events ALTER COLUMN previous_hash SET NOT NULL")
    op.execute("ALTER TABLE public.audit_events ALTER COLUMN event_hash SET NOT NULL")
    op.execute("CREATE TRIGGER audit_hash_insert BEFORE INSERT ON public.audit_events FOR EACH ROW EXECUTE FUNCTION public.app_audit_hash_insert()")
    # Only auditor role can verify; the function doesn't expose the signing key.
    op.execute("""CREATE FUNCTION public.app_verify_audit_chain() RETURNS boolean
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE tenant uuid; staff uuid; role_name text; r record;
              prior text := repeat('0',64); secret bytea; payload text; digest text;
      BEGIN
        tenant := public.app_current_tenant(); staff := public.app_current_staff();
        IF tenant IS NULL OR staff IS NULL THEN RAISE EXCEPTION 'not authorized'; END IF;
        SELECT s.role INTO role_name FROM public.staff_users s
          WHERE s.id=staff AND s.tenant_id=tenant;
        IF role_name IS DISTINCT FROM 'auditor' THEN RAISE EXCEPTION 'auditor required'; END IF;
        SELECT k.secret INTO secret FROM app_private.context_key k WHERE k.id=1;
        FOR r IN SELECT * FROM public.audit_events a WHERE a.tenant_id=tenant
          ORDER BY a.chain_sequence LOOP
          payload := concat_ws('|',prior,r.id::text,r.tenant_id::text,r.actor_id::text,
            COALESCE(r.patient_id::text,''),r.action,
            to_char(r.occurred_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US'),
            COALESCE(r.reason,''));
          digest := encode(public.hmac(convert_to(payload,'UTF8'),secret,'sha256'),'hex');
          IF r.previous_hash IS DISTINCT FROM prior OR r.event_hash IS DISTINCT FROM digest
            THEN RETURN false; END IF;
          prior := r.event_hash;
        END LOOP;
        RETURN true;
      END $$""")
    op.execute('REVOKE ALL ON FUNCTION public.app_verify_audit_chain() FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION public.app_verify_audit_chain() TO patient_monitoring_runtime')
    # Prevent caller-supplied chain fields from being persisted; trigger overwrites them.


def downgrade():
    raise RuntimeError('Audit integrity migration downgrade requires reviewed retention plan')

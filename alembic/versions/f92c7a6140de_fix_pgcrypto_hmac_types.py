"""Fix pgcrypto hmac input type for signed tenant context.

Revision ID: f92c7a6140de
Revises: e4b6c8a19d32
"""
from alembic import op

revision = "f92c7a6140de"
down_revision = "e4b6c8a19d32"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE OR REPLACE FUNCTION public.app_current_tenant() RETURNS uuid\n        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$\n        DECLARE tenant_text text; signature text; expected text; secret bytea;\n        BEGIN\n          tenant_text := current_setting('app.tenant_id', true);\n          signature := current_setting('app.tenant_signature', true);\n          IF tenant_text IS NULL OR tenant_text = '' OR signature IS NULL THEN RETURN NULL; END IF;\n          SELECT k.secret INTO secret FROM app_private.context_key k WHERE k.id=1;\n          expected := encode(public.hmac(convert_to(tenant_text || ':' || pg_backend_pid()::text || ':' || txid_current()::text, 'UTF8'), secret, 'sha256'),'hex');\n          IF signature <> expected THEN RETURN NULL; END IF;\n          RETURN tenant_text::uuid;\n        END $$")
    op.execute("CREATE OR REPLACE FUNCTION public.app_authorize_device(p_device uuid,p_digest text) RETURNS uuid\n        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$\n        DECLARE found_tenant uuid; secret bytea; signature text;\n        BEGIN\n          SELECT d.tenant_id INTO found_tenant FROM public.devices d\n          WHERE d.id=p_device AND d.token_hash=p_digest;\n          IF found_tenant IS NULL THEN RETURN NULL; END IF;\n          SELECT k.secret INTO secret FROM app_private.context_key k WHERE k.id=1;\n          signature := encode(public.hmac(convert_to(found_tenant::text || ':' || pg_backend_pid()::text || ':' || txid_current()::text, 'UTF8'), secret, 'sha256'),'hex');\n          PERFORM set_config('app.tenant_id',found_tenant::text,true);\n          PERFORM set_config('app.tenant_signature',signature,true);\n          RETURN found_tenant;\n        END $$")


def downgrade():
    # The corrected implementation is retained on downgrade to avoid reintroducing
    # a runtime authentication failure. Both function signatures remain unchanged.
    pass

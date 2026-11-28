"""Add durable evaluation storage and a separate, initially unprivileged processor role."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "2c3d4e5f6071"
down_revision = "1b2c3d4e5f60"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("alerts", sa.Column("episode_end", sa.DateTime(timezone=True)))
    op.add_column("alerts", sa.Column("qualified_at", sa.DateTime(timezone=True)))
    op.add_column("alerts", sa.Column("is_retrospective", sa.Boolean()))
    op.add_column("alerts", sa.Column("superseded_by_id", pg.UUID(as_uuid=True)))
    op.create_unique_constraint("uq_alert_patient_id", "alerts", ["tenant_id", "patient_id", "id"])
    op.create_foreign_key("fk_alert_superseded", "alerts", "alerts",
        ["tenant_id", "patient_id", "superseded_by_id"], ["tenant_id", "patient_id", "id"])
    op.drop_constraint("ck_alert_status", "alerts", type_="check")
    op.create_check_constraint("ck_alert_status", "alerts", "status IN ('open','acknowledged','resolved','retracted','superseded')")
    op.create_check_constraint("ck_alert_episode_end", "alerts", "episode_end IS NULL OR episode_end >= episode_start")
    op.create_table("pending_alert_evaluations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False),
        sa.Column("evaluation_now", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.ForeignKeyConstraint(["tenant_id", "patient_id"], ["patients.tenant_id", "patients.id"]),
        sa.CheckConstraint("cardinality(observation_ids) > 0", name="ck_pending_nonempty"))
    op.create_index("ix_pending_created", "pending_alert_evaluations", ["created_at", "id"])
    op.create_index("ix_pending_patient", "pending_alert_evaluations", ["tenant_id", "patient_id"])
    op.execute("ALTER TABLE public.pending_alert_evaluations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.pending_alert_evaluations FORCE ROW LEVEL SECURITY")
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='patient_monitoring_alert_processor') THEN
            CREATE ROLE patient_monitoring_alert_processor NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOINHERIT;
        END IF;
    END $$""")
    # No data grants until the scoped processing interface is implemented.
    op.execute("GRANT USAGE ON SCHEMA public TO patient_monitoring_alert_processor")


def downgrade():
    raise RuntimeError("Alert foundation downgrade requires explicit data-preservation review")

"""Staff identities and care team memberships.

Revision ID: c39d0b0b124a
Revises: b18d9a1f6c23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
revision = "c39d0b0b124a"
down_revision = "b18d9a1f6c23"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("staff_users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_staff_tenant_id"),
        sa.CheckConstraint("role IN ('clinician', 'auditor')", name="ck_staff_role"))
    op.create_table("care_team_memberships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("staff_id", UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "staff_id"], ["staff_users.tenant_id", "staff_users.id"], name="fk_care_staff_tenant"),
        sa.ForeignKeyConstraint(["tenant_id", "patient_id"], ["patients.tenant_id", "patients.id"], name="fk_care_patient_tenant"),
        sa.UniqueConstraint("staff_id", "patient_id", name="uq_care_staff_patient"))
    op.create_index("ix_care_team_tenant_patient", "care_team_memberships", ["tenant_id", "patient_id"])

def downgrade():
    op.drop_index("ix_care_team_tenant_patient", table_name="care_team_memberships")
    op.drop_table("care_team_memberships")
    op.drop_table("staff_users")

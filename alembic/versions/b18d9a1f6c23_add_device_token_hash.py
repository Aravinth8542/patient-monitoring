"""Store hashed device credentials (existing devices require provisioning).

Revision ID: b18d9a1f6c23
Revises: 955a60636694
"""
from alembic import op
import sqlalchemy as sa

revision = "b18d9a1f6c23"
down_revision = "955a60636694"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("devices", sa.Column("token_hash", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_device_token_hash", "devices", ["token_hash"])

def downgrade():
    op.drop_constraint("uq_device_token_hash", "devices", type_="unique")
    op.drop_column("devices", "token_hash")

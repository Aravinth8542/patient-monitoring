"""Track database insertion time independently of simulated receipt time.

Revision ID: 1b2c3d4e5f60
Revises: c9e0f1a2b345
"""
from alembic import op
import sqlalchemy as sa

revision = "1b2c3d4e5f60"
down_revision = "c9e0f1a2b345"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("observations", sa.Column(
        "inserted_at", sa.DateTime(timezone=True), nullable=False,
        server_default=sa.text("clock_timestamp()"),
    ))


def downgrade():
    op.drop_column("observations", "inserted_at")

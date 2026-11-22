"""Record when monitoring starts, independently of the first upload.

Revision ID: a7c8d9e0f112
Revises: f6a7b8c9d0e1
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7c8d9e0f112'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    # Existing patients begin monitoring at migration time; there is no
    # trustworthy historical enrollment timestamp to backfill.
    op.add_column('patients', sa.Column('monitoring_started_at',
        sa.DateTime(timezone=True), nullable=False,
        server_default=sa.text('CURRENT_TIMESTAMP')))


def downgrade():
    op.drop_column('patients', 'monitoring_started_at')

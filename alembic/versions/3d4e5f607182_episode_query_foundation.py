"""Add episode anchor timestamp and metric-specific ordered lookup index."""
from alembic import op
import sqlalchemy as sa
revision = '3d4e5f607182'
down_revision = '2c3d4e5f6071'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('alerts', sa.Column('last_observation_at', sa.DateTime(timezone=True)))
    op.create_index('ix_observation_patient_metric_time_id', 'observations',
                    ['tenant_id', 'patient_id', 'type', 'effective_at', 'id'])


def downgrade():
    op.drop_index('ix_observation_patient_metric_time_id', table_name='observations')
    op.drop_column('alerts', 'last_observation_at')

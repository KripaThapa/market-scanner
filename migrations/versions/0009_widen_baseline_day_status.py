"""Allow the explicit completed-with-failures baseline day state.

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('baseline_days') as batch:
        batch.alter_column('status', existing_type=sa.String(20),
                           type_=sa.String(32), existing_nullable=False)


def downgrade():
    with op.batch_alter_table('baseline_days') as batch:
        batch.alter_column('status', existing_type=sa.String(32),
                           type_=sa.String(20), existing_nullable=False)

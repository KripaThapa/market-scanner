"""Add durable watchlist processing claims and recovery metadata.

Revision ID: 0011
Revises: 0010
"""

from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('watchlist_uploads') as batch:
        batch.add_column(sa.Column('processing_claimed_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('processing_attempts', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('watchlist_uploads') as batch:
        batch.drop_column('processing_attempts')
        batch.drop_column('processing_claimed_at')

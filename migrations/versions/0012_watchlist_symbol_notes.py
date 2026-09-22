"""Preserve original OCR note text for validated watchlist rows.

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('watchlist_symbols') as batch:
        batch.add_column(sa.Column('original_note', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('watchlist_symbols') as batch:
        batch.drop_column('original_note')

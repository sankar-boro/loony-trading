"""add signal_outcomes

Revision ID: c7e2a1d9b5f3
Revises: b3d1e7c2a9f4
Create Date: 2026-10-18 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e2a1d9b5f3'
down_revision: Union[str, Sequence[str], None] = 'b3d1e7c2a9f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('signal_outcomes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('signal_id', sa.Integer(), nullable=False),
    sa.Column('signal_date', sa.String(length=10), nullable=False),
    sa.Column('entry_price', sa.Float(), nullable=False),
    sa.Column('ret_1d', sa.Float(), nullable=True),
    sa.Column('ret_5d', sa.Float(), nullable=True),
    sa.Column('ret_20d', sa.Float(), nullable=True),
    sa.Column('setup_result', sa.String(length=16), nullable=True),
    sa.Column('setup_bars', sa.Integer(), nullable=True),
    sa.Column('complete', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['signal_id'], ['signals.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('signal_id')
    )
    op.create_index(op.f('ix_signal_outcomes_signal_date'), 'signal_outcomes', ['signal_date'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_signal_outcomes_signal_date'), table_name='signal_outcomes')
    op.drop_table('signal_outcomes')

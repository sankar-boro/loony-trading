"""add doc_chapters and doc_sections (the handbook)

Revision ID: b3d1e7c2a9f4
Revises: a89ec2781941
Create Date: 2026-10-12 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d1e7c2a9f4'
down_revision: Union[str, Sequence[str], None] = 'a89ec2781941'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. The tables may already exist if scripts/migrate_docs.py
    (db/sql/handbook.sql) created them first; then there is nothing to do."""
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('doc_chapters') and inspector.has_table('doc_sections'):
        return
    op.create_table('doc_chapters',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('path', sa.String(length=255), nullable=False),
    sa.Column('part', sa.String(length=128), nullable=False),
    sa.Column('part_number', sa.Integer(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('path')
    )
    op.create_index(op.f('ix_doc_chapters_number'), 'doc_chapters', ['number'], unique=False)
    op.create_table('doc_sections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('chapter_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('anchor', sa.String(length=255), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['chapter_id'], ['doc_chapters.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('chapter_id', 'position', name='uq_docsection_chapter_position')
    )
    op.create_index(op.f('ix_doc_sections_chapter_id'), 'doc_sections', ['chapter_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_doc_sections_chapter_id'), table_name='doc_sections')
    op.drop_table('doc_sections')
    op.drop_index(op.f('ix_doc_chapters_number'), table_name='doc_chapters')
    op.drop_table('doc_chapters')

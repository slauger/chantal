"""Add views tables (View, ViewRepository, ViewSnapshot)

Revision ID: 3c10bed2aae6
Revises: 
Create Date: 2026-01-10 16:17:03.115693

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c10bed2aae6'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create views table
    op.create_table(
        'views',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('repo_type', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('is_published', sa.Boolean(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('published_path', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_views_name'), 'views', ['name'], unique=False)

    # Create view_repositories junction table
    op.create_table(
        'view_repositories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('view_id', sa.Integer(), nullable=False),
        sa.Column('repository_id', sa.Integer(), nullable=False),
        sa.Column('order', sa.Integer(), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ),
        sa.ForeignKeyConstraint(['view_id'], ['views.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('view_id', 'repository_id', name='uq_view_repository')
    )

    # Create view_snapshots table
    op.create_table(
        'view_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('view_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('snapshot_ids', sa.JSON(), nullable=False),
        sa.Column('is_published', sa.Boolean(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('published_path', sa.Text(), nullable=True),
        sa.Column('package_count', sa.Integer(), nullable=False),
        sa.Column('total_size_bytes', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['view_id'], ['views.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('view_id', 'name', name='uq_view_snapshot_name')
    )
    op.create_index(op.f('ix_view_snapshots_name'), 'view_snapshots', ['name'], unique=False)


def downgrade() -> None:
    # Drop tables in reverse order (foreign key constraints)
    op.drop_index(op.f('ix_view_snapshots_name'), table_name='view_snapshots')
    op.drop_table('view_snapshots')
    op.drop_table('view_repositories')
    op.drop_index(op.f('ix_views_name'), table_name='views')
    op.drop_table('views')

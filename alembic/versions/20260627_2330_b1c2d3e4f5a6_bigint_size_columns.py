"""widen size/bytes columns to BigInteger

Integer (int4) overflows on PostgreSQL for files larger than 2 GiB and for the
multi-GiB aggregate counters of any real mirror. Widen them to BigInteger.

Revision ID: b1c2d3e4f5a6
Revises: e190d159daac
Create Date: 2026-06-27 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "e190d159daac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column) pairs that hold byte sizes/aggregates.
_COLUMNS = [
    ("content_items", "size_bytes"),
    ("repository_files", "size_bytes"),
    ("snapshots", "total_size_bytes"),
    ("sync_history", "bytes_downloaded"),
    ("view_snapshots", "total_size_bytes"),
]


def upgrade() -> None:
    # batch mode so this also works on SQLite (which recreates the table).
    for table, column in _COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, type_=sa.BigInteger(), existing_nullable=False)


def downgrade() -> None:
    for table, column in _COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, type_=sa.Integer(), existing_nullable=False)

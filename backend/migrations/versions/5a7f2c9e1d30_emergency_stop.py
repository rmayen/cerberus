"""emergency stop switch

Revision ID: 5a7f2c9e1d30
Revises: 3c9d1e7a5b20
Create Date: 2026-10-29 09:00:00

Adds a new table. Existing tables and rows are not changed.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "5a7f2c9e1d30"
down_revision: str | Sequence[str] | None = "3c9d1e7a5b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "emergency_stop",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Seed the single switch row as off, so the first admin change is an update, not a racing insert.
    stop = sa.table(
        "emergency_stop",
        sa.column("id", sa.Integer),
        sa.column("active", sa.Boolean),
        sa.column("changed_by", sa.Integer),
        sa.column("changed_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        stop,
        [{"id": 1, "active": False, "changed_by": None, "changed_at": datetime.now(UTC)}],
    )


def downgrade() -> None:
    op.drop_table("emergency_stop")

"""analysis jobs: worker leases and requested timeout

Revision ID: 7c1e4b2d9a80
Revises: 5a7f2c9e1d30
Create Date: 2026-10-29 14:00:00

Adds nullable lease columns, which hold NULL for jobs no worker has claimed, and the requested
execution timeout. Existing rows get the 60-second default that the API used before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c1e4b2d9a80"
down_revision: str | Sequence[str] | None = "5a7f2c9e1d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("lease_owner", sa.String(length=64), nullable=True))
    op.add_column(
        "analysis_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="60"),
    )


def downgrade() -> None:
    with op.batch_alter_table("analysis_jobs") as batch:
        batch.drop_column("timeout_seconds")
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_owner")

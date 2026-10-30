"""differential analyses: queued orchestration

Revision ID: b4e8a1c3d572
Revises: 7c1e4b2d9a80
Create Date: 2026-10-29 16:00:00

Adds the requested variations and timeout to differential analyses, and the role and variation to
the child jobs that the worker runs. Existing rows keep NULL, and their analyses are already
finished, so nothing needs backfilling.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4e8a1c3d572"
down_revision: str | Sequence[str] | None = "7c1e4b2d9a80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("differential_analyses", sa.Column("variations", sa.JSON(), nullable=True))
    op.add_column(
        "differential_analyses",
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="60"),
    )
    op.add_column(
        "analysis_jobs", sa.Column("differential_role", sa.String(length=16), nullable=True)
    )
    op.add_column("analysis_jobs", sa.Column("differential_variation", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("analysis_jobs") as batch:
        batch.drop_column("differential_variation")
        batch.drop_column("differential_role")
    with op.batch_alter_table("differential_analyses") as batch:
        batch.drop_column("timeout_seconds")
        batch.drop_column("variations")

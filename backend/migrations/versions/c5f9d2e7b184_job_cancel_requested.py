"""analysis jobs: cancel request for running jobs

Revision ID: c5f9d2e7b184
Revises: b4e8a1c3d572
Create Date: 2026-10-29 18:00:00

Adds cancel_requested. Existing rows get false, so no job has a pending cancellation.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5f9d2e7b184"
down_revision: str | Sequence[str] | None = "b4e8a1c3d572"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_jobs",
        sa.Column(
            "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("analysis_jobs") as batch:
        batch.drop_column("cancel_requested")

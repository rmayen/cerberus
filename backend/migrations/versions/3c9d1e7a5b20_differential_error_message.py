"""differential analyses: error message

Revision ID: 3c9d1e7a5b20
Revises: 8585e3a8f939
Create Date: 2026-10-28 12:00:00

Adds a nullable column. Existing rows keep NULL, which means no failure message.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c9d1e7a5b20"
down_revision: str | Sequence[str] | None = "8585e3a8f939"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "differential_analyses",
        sa.Column("error_message", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("differential_analyses") as batch:
        batch.drop_column("error_message")

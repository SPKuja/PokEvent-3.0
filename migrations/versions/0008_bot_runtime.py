"""Track live Discord bot runtime information.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_runtime",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("bot_user_id", sa.String(length=32), nullable=True),
        sa.Column("bot_name", sa.String(length=255), nullable=True),
        sa.Column(
            "guild_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bot_runtime")

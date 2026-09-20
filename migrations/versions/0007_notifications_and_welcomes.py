"""Add event mention and member welcome settings.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guild_configs",
        sa.Column("event_mention_mode", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "guild_configs",
        sa.Column("event_mention_role_ids", sa.JSON(), nullable=True),
    )
    op.add_column(
        "guild_configs",
        sa.Column("welcome_mode", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "guild_configs",
        sa.Column("welcome_channel_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "guild_configs",
        sa.Column("welcome_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guild_configs", "welcome_message")
    op.drop_column("guild_configs", "welcome_channel_id")
    op.drop_column("guild_configs", "welcome_mode")
    op.drop_column("guild_configs", "event_mention_role_ids")
    op.drop_column("guild_configs", "event_mention_mode")

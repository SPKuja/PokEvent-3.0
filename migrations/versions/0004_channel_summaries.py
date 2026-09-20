"""Add pinned upcoming-event channel summaries.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_configs.guild_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id",
            "channel_id",
            name="uq_channel_summary_guild_channel",
        ),
    )


def downgrade() -> None:
    op.drop_table("channel_summaries")

"""Add opt-in cross-channel spam protection for Discord servers.

Revision ID: 0014
Revises: 0013
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guild_configs",
        sa.Column(
            "spam_protection_enabled", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "guild_configs",
        sa.Column(
            "spam_timeout_enabled", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "guild_configs",
        sa.Column(
            "spam_alerts_enabled", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "guild_configs",
        sa.Column("spam_alert_channel_id", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guild_configs", "spam_alert_channel_id")
    op.drop_column("guild_configs", "spam_alerts_enabled")
    op.drop_column("guild_configs", "spam_timeout_enabled")
    op.drop_column("guild_configs", "spam_protection_enabled")

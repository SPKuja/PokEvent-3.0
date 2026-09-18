"""Add per-guild League registry and event channel configuration.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guild_configs",
        sa.Column("default_league_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "guild_configs",
        sa.Column("default_channel_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "guild_configs",
        sa.Column("all_channel_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "guild_configs",
        sa.Column(
            "leagues_seeded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_table(
        "guild_leagues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_key", sa.String(length=255), nullable=False),
        sa.Column("league_id", sa.String(length=255), nullable=False),
        sa.Column("channel_id", sa.String(length=32), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_configs.guild_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "name_key", name="uq_guild_league_name"),
        sa.UniqueConstraint("guild_id", "league_id", name="uq_guild_league_id"),
    )

    op.add_column(
        "routes",
        sa.Column("baseline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_route_guild_league",
        "routes",
        ["guild_id", "upstream_organisation_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_route_guild_league", "routes", type_="unique")
    op.drop_column("routes", "baseline_at")
    op.drop_table("guild_leagues")
    op.drop_column("guild_configs", "leagues_seeded")
    op.drop_column("guild_configs", "all_channel_id")
    op.drop_column("guild_configs", "default_channel_id")
    op.drop_column("guild_configs", "default_league_id")

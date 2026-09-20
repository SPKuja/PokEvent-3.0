"""Add guild-owned community event fields.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("owner_guild_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("created_by_user_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column(
            "public_visible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_index(
        "ix_events_owner_guild_id",
        "events",
        ["owner_guild_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_events_owner_guild_id", table_name="events")
    op.drop_column("events", "public_visible")
    op.drop_column("events", "description")
    op.drop_column("events", "created_by_user_id")
    op.drop_column("events", "owner_guild_id")

"""Discord-server League claims and manual event overrides.

Revision ID: 0013
Revises: 0012
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "league_claims",
        sa.Column("guild_id", sa.String(32), primary_key=True),
        sa.Column("league_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("owner_user_id", sa.String(32), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by_user_id", sa.String(32)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_league_claims_league_id", "league_claims", ["league_id"])
    op.create_index(
        "uq_approved_claim_league", "league_claims", ["league_id"], unique=True,
        postgresql_where=sa.text("status = 'approved'"),
        sqlite_where=sa.text("status = 'approved'"),
    )
    op.create_table(
        "manual_event_overrides",
        sa.Column(
            "event_id", sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("league_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32)),
        sa.Column("title", sa.String(500)),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("venue_name", sa.String(255)),
        sa.Column("updated_by_user_id", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_manual_event_overrides_league_id",
        "manual_event_overrides", ["league_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_manual_event_overrides_league_id", table_name="manual_event_overrides")
    op.drop_table("manual_event_overrides")
    op.drop_index("uq_approved_claim_league", table_name="league_claims")
    op.drop_index("ix_league_claims_league_id", table_name="league_claims")
    op.drop_table("league_claims")

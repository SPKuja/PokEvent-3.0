"""Optional daily event verification records.

Revision ID: 0012
Revises: 0011
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verification_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("league_id", sa.String(255), nullable=False),
        sa.Column("tournament_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("venue_name", sa.String(255)),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "league_id", "tournament_id",
            name="uq_verified_league_tournament",
        ),
    )
    op.create_index(
        op.f("ix_verification_records_league_id"),
        "verification_records", ["league_id"], unique=False,
    )
    op.create_table(
        "verification_checkpoints",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("verification_checkpoints")
    op.drop_index(
        op.f("ix_verification_records_league_id"),
        table_name="verification_records",
    )
    op.drop_table("verification_records")

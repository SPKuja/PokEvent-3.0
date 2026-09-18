"""Initial PokEvent 3.0 catalogue and Discord routing schema.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("upstream_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "upstream_id", name="uq_organisation_source_upstream"),
    )

    op.create_table(
        "guild_configs",
        sa.Column("guild_id", sa.String(length=32), nullable=False),
        sa.Column("home_name", sa.String(length=255), nullable=True),
        sa.Column("home_latitude", sa.Float(), nullable=True),
        sa.Column("home_longitude", sa.Float(), nullable=True),
        sa.Column("default_radius_miles", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("guild_id"),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("upstream_event_id", sa.String(length=255), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=True),
        sa.Column("upstream_organisation_id", sa.String(length=255), nullable=True),
        sa.Column("upstream_location_id", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("game", sa.String(length=32), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("venue_name", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("postcode", sa.String(length=32), nullable=True),
        sa.Column("country", sa.String(length=64), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("registration_url", sa.Text(), nullable=True),
        sa.Column("upstream_payload", sa.JSON(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "upstream_event_id", name="uq_event_source_upstream"),
    )

    op.create_table(
        "routes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=True),
        sa.Column("upstream_organisation_id", sa.String(length=255), nullable=True),
        sa.Column("upstream_location_id", sa.String(length=255), nullable=True),
        sa.Column("game", sa.String(length=32), nullable=True),
        sa.Column("centre_latitude", sa.Float(), nullable=True),
        sa.Column("centre_longitude", sa.Float(), nullable=True),
        sa.Column("max_distance_miles", sa.Float(), nullable=True),
        sa.Column("announce_new", sa.Boolean(), nullable=False),
        sa.Column("announce_updates", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guild_configs.guild_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "published_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("route_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=32), nullable=False),
        sa.Column("last_content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("route_id", "event_id", name="uq_published_route_event"),
    )


def downgrade() -> None:
    op.drop_table("published_messages")
    op.drop_table("routes")
    op.drop_table("events")
    op.drop_table("guild_configs")
    op.drop_table("organisations")

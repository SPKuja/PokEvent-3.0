from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Organisation(Base):
    __tablename__ = "organisations"
    __table_args__ = (
        UniqueConstraint("source", "upstream_id", name="uq_organisation_source_upstream"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    upstream_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("source", "upstream_event_id", name="uq_event_source_upstream"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    upstream_event_id: Mapped[str] = mapped_column(String(255), nullable=False)

    organisation_id: Mapped[str | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="SET NULL")
    )
    upstream_organisation_id: Mapped[str | None] = mapped_column(String(255))
    upstream_location_id: Mapped[str | None] = mapped_column(String(255))

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    game: Mapped[str | None] = mapped_column(String(32))
    event_type: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="active")

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    venue_name: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(128))
    postcode: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(64))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    source_url: Mapped[str | None] = mapped_column(Text)
    registration_url: Mapped[str | None] = mapped_column(Text)
    upstream_payload: Mapped[dict | None] = mapped_column(JSON)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class GuildConfig(Base):
    __tablename__ = "guild_configs"

    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    home_name: Mapped[str | None] = mapped_column(String(255))
    home_latitude: Mapped[float | None] = mapped_column(Float)
    home_longitude: Mapped[float | None] = mapped_column(Float)
    default_radius_miles: Mapped[float | None] = mapped_column(Float)

    default_league_id: Mapped[str | None] = mapped_column(String(255))
    default_channel_id: Mapped[str | None] = mapped_column(String(32))
    all_channel_id: Mapped[str | None] = mapped_column(String(32))
    card_event_types: Mapped[list[str] | None] = mapped_column(JSON)
    event_mention_mode: Mapped[str | None] = mapped_column(String(16))
    event_mention_role_ids: Mapped[list[str] | None] = mapped_column(JSON)
    welcome_mode: Mapped[str | None] = mapped_column(String(16))
    welcome_channel_id: Mapped[str | None] = mapped_column(String(32))
    welcome_message: Mapped[str | None] = mapped_column(Text)
    leagues_seeded: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class GuildLeague(Base):
    __tablename__ = "guild_leagues"
    __table_args__ = (
        UniqueConstraint("guild_id", "name_key", name="uq_guild_league_name"),
        UniqueConstraint("guild_id", "league_id", name="uq_guild_league_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(
        ForeignKey("guild_configs.guild_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_key: Mapped[str] = mapped_column(String(255), nullable=False)
    league_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_id: Mapped[str | None] = mapped_column(String(32))
    origin: Mapped[str] = mapped_column(String(32), default="server")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Route(Base):
    __tablename__ = "routes"
    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "upstream_organisation_id",
            name="uq_route_guild_league",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(
        ForeignKey("guild_configs.guild_id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)

    organisation_id: Mapped[str | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE")
    )
    upstream_organisation_id: Mapped[str | None] = mapped_column(String(255))
    upstream_location_id: Mapped[str | None] = mapped_column(String(255))
    game: Mapped[str | None] = mapped_column(String(32))

    centre_latitude: Mapped[float | None] = mapped_column(Float)
    centre_longitude: Mapped[float | None] = mapped_column(Float)
    max_distance_miles: Mapped[float | None] = mapped_column(Float)

    announce_new: Mapped[bool] = mapped_column(Boolean, default=True)
    announce_updates: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    baseline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PublishedMessage(Base):
    __tablename__ = "published_messages"
    __table_args__ = (
        UniqueConstraint("route_id", "event_id", name="uq_published_route_event"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    message_id: Mapped[str] = mapped_column(String(32), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(32))
    last_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_event_snapshot: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )



class ChannelSummary(Base):
    __tablename__ = "channel_summaries"
    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "channel_id",
            name="uq_channel_summary_guild_channel",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(
        ForeignKey("guild_configs.guild_id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    message_id: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )



class BotRuntime(Base):
    __tablename__ = "bot_runtime"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    bot_user_id: Mapped[str | None] = mapped_column(String(32))
    bot_name: Mapped[str | None] = mapped_column(String(255))
    guild_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

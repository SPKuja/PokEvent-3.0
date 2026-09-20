from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Event, utcnow

COMMUNITY_SOURCE = "community"
COMMUNITY_GAMES = {"tcg", "vgc", "go", "other"}


def parse_local_datetime(value: str, timezone_name: str) -> datetime:
    cleaned = " ".join(value.strip().split())
    try:
        local = datetime.strptime(cleaned, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Use date/time format YYYY-MM-DD HH:MM.") from exc

    try:
        timezone = ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError("PokÈvent's local timezone is not configured correctly.") from exc

    return local.replace(tzinfo=timezone).astimezone(UTC)


def normalise_game(value: str) -> str:
    cleaned = value.strip().casefold().replace("pokémon ", "").replace("pokemon ", "")
    aliases = {
        "cards": "tcg",
        "card": "tcg",
        "tcg": "tcg",
        "vgc": "vgc",
        "video game": "vgc",
        "video games": "vgc",
        "go": "go",
        "pokemon go": "go",
        "pokémon go": "go",
        "other": "other",
    }
    game = aliases.get(cleaned)
    if game not in COMMUNITY_GAMES:
        raise ValueError("Game must be TCG, VGC, GO or Other.")
    return game


def normalise_optional_url(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Registration/details link must be a valid http(s) URL.")
    return cleaned


def community_event_content_hash(event: Event) -> str:
    payload = {
        "owner_guild_id": event.owner_guild_id,
        "upstream_organisation_id": event.upstream_organisation_id,
        "title": event.title,
        "description": event.description,
        "game": event.game,
        "event_type": event.event_type,
        "status": event.status,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
        "venue_name": event.venue_name,
        "address": event.address,
        "city": event.city,
        "postcode": event.postcode,
        "registration_url": event.registration_url,
        "public_visible": event.public_visible,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def touch_community_event(event: Event) -> None:
    event.content_hash = community_event_content_hash(event)
    event.last_seen_at = utcnow()


async def create_community_event(
    session: AsyncSession,
    *,
    guild_id: str,
    creator_user_id: str,
    league_id: str,
    title: str,
    starts_at: datetime,
    game: str,
    event_type: str,
    venue_name: str | None,
) -> Event:
    cleaned_title = " ".join(title.strip().split())
    if not cleaned_title:
        raise ValueError("Event title is required.")

    cleaned_type = " ".join(event_type.strip().split())
    if not cleaned_type:
        cleaned_type = "Community Event"

    event = Event(
        source=COMMUNITY_SOURCE,
        upstream_event_id=str(uuid4()),
        owner_guild_id=guild_id,
        created_by_user_id=creator_user_id,
        public_visible=False,
        upstream_organisation_id=league_id,
        title=cleaned_title[:500],
        game=normalise_game(game),
        event_type=cleaned_type[:128],
        status="active",
        starts_at=starts_at,
        venue_name=(" ".join(venue_name.strip().split())[:255] if venue_name else None),
        content_hash="",
    )
    touch_community_event(event)
    session.add(event)
    await session.flush()
    return event


async def owned_community_event(
    session: AsyncSession,
    *,
    guild_id: str,
    event_id: str,
) -> Event:
    event = await session.scalar(
        select(Event).where(
            Event.id == event_id,
            Event.source == COMMUNITY_SOURCE,
            Event.owner_guild_id == guild_id,
        )
    )
    if event is None:
        raise ValueError("That community event does not belong to this server.")
    return event


async def list_community_events(
    session: AsyncSession,
    *,
    guild_id: str,
    include_recent: bool = True,
) -> list[Event]:
    cutoff = datetime.now(UTC) - timedelta(days=30) if include_recent else datetime.now(UTC)
    return list(
        (
            await session.scalars(
                select(Event)
                .where(
                    Event.source == COMMUNITY_SOURCE,
                    Event.owner_guild_id == guild_id,
                    Event.starts_at >= cutoff,
                )
                .order_by(Event.starts_at)
            )
        ).all()
    )


async def update_community_event_core(
    session: AsyncSession,
    *,
    guild_id: str,
    event_id: str,
    title: str,
    starts_at: datetime,
    game: str,
    event_type: str,
    venue_name: str | None,
) -> Event:
    event = await owned_community_event(session, guild_id=guild_id, event_id=event_id)
    event.title = " ".join(title.strip().split())[:500]
    if not event.title:
        raise ValueError("Event title is required.")
    event.starts_at = starts_at
    event.game = normalise_game(game)
    event.event_type = (" ".join(event_type.strip().split()) or "Community Event")[:128]
    event.venue_name = (
        " ".join(venue_name.strip().split())[:255]
        if venue_name and venue_name.strip()
        else None
    )
    if event.ends_at is not None and event.ends_at <= starts_at:
        event.ends_at = None
    touch_community_event(event)
    await session.flush()
    return event


async def update_community_event_details(
    session: AsyncSession,
    *,
    guild_id: str,
    event_id: str,
    ends_at: datetime | None,
    address: str | None,
    description: str | None,
    registration_url: str | None,
) -> Event:
    event = await owned_community_event(session, guild_id=guild_id, event_id=event_id)
    if ends_at is not None and ends_at <= event.starts_at:
        raise ValueError("End time must be after the event start time.")

    event.ends_at = ends_at
    event.address = address.strip()[:2000] if address and address.strip() else None
    event.description = (
        description.strip()[:2000] if description and description.strip() else None
    )
    event.registration_url = normalise_optional_url(registration_url)
    touch_community_event(event)
    await session.flush()
    return event


async def move_community_event(
    session: AsyncSession,
    *,
    guild_id: str,
    event_id: str,
    league_id: str,
) -> Event:
    event = await owned_community_event(session, guild_id=guild_id, event_id=event_id)
    event.upstream_organisation_id = league_id
    touch_community_event(event)
    await session.flush()
    return event


async def cancel_community_event(
    session: AsyncSession,
    *,
    guild_id: str,
    event_id: str,
) -> Event:
    event = await owned_community_event(session, guild_id=guild_id, event_id=event_id)
    event.status = "cancelled"
    touch_community_event(event)
    await session.flush()
    return event

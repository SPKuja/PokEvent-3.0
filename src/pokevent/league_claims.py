"""Server-level ownership claims and league-scoped manual corrections.

Being followed by a server never grants ownership. Only an owner-initiated,
PokEvent-owner-approved claim allows administrators to change that League.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .catalogue import event_content_hash
from .domain import EventSnapshot, EventStatus
from .models import (
    Event,
    GuildConfig,
    LeagueClaim,
    ManualEventOverride,
    Organisation,
    utcnow,
)

ACTIVE_CLAIM_STATES = {"invited", "pending", "approved"}
ALLOWED_FIELDS = {"status", "title", "starts_at", "venue_name", "ends_at"}
EDITABLE_FIELDS = ALLOWED_FIELDS - {"ends_at"}


async def approved_for_league(
    session: AsyncSession, league_id: str,
) -> LeagueClaim | None:
    return await session.scalar(
        select(LeagueClaim).where(
            LeagueClaim.league_id == league_id,
            LeagueClaim.status == "approved",
        )
    )


async def invite_server_owner(
    session: AsyncSession, guild_id: str, league_id: str, owner_id: str,
) -> bool:
    """Record one invitation for the currently configured default League."""
    config = await session.get(GuildConfig, guild_id)
    if config is None or config.default_league_id != league_id:
        return False
    existing = await session.get(LeagueClaim, guild_id)
    if existing is not None:
        if existing.status in ACTIVE_CLAIM_STATES:
            return False
        if existing.status in {"declined", "rejected"} and existing.league_id == league_id:
            return False
    if await approved_for_league(session, league_id) is not None:
        return False
    if existing is None:
        session.add(LeagueClaim(
            guild_id=guild_id, league_id=league_id,
            owner_user_id=owner_id, status="invited",
        ))
    else:
        existing.league_id = league_id
        existing.owner_user_id = owner_id
        existing.status = "invited"
    await session.flush()
    return True


async def request_claim(
    session: AsyncSession, guild_id: str, owner_id: str,
) -> LeagueClaim:
    """Only the caller-verified Discord owner may submit a request."""
    config = await session.get(GuildConfig, guild_id)
    if config is None or not config.default_league_id:
        raise ValueError("Set this server's default League before claiming it.")
    league_id = config.default_league_id
    other = await approved_for_league(session, league_id)
    if other is not None and other.guild_id != guild_id:
        raise ValueError("That League is already claimed by another Discord server.")
    claim = await session.get(LeagueClaim, guild_id)
    if claim and claim.status == "approved":
        raise ValueError("This Discord server already has a verified League.")
    if claim and claim.status == "pending":
        raise ValueError("This server already has a claim awaiting approval.")
    if claim and claim.status == "rejected" and claim.league_id == league_id:
        raise ValueError("This claim was declined by the PokEvent owner. Contact them to appeal.")
    if claim is None:
        claim = LeagueClaim(
            guild_id=guild_id, league_id=league_id, owner_user_id=owner_id,
        )
        session.add(claim)
    claim.league_id = league_id
    claim.owner_user_id = owner_id
    claim.status = "pending"
    claim.requested_at = utcnow()
    claim.reviewed_at = None
    claim.reviewed_by_user_id = None
    await session.flush()
    return claim


async def decline_invitation(
    session: AsyncSession, guild_id: str, owner_id: str,
) -> None:
    claim = await session.get(LeagueClaim, guild_id)
    if claim is None:
        config = await session.get(GuildConfig, guild_id)
        if config is None or not config.default_league_id:
            raise ValueError("There is no League to decline.")
        claim = LeagueClaim(
            guild_id=guild_id, league_id=config.default_league_id,
            owner_user_id=owner_id, status="declined",
        )
        session.add(claim)
    elif claim.status not in {"invited", "delivery_failed", "declined"} or claim.owner_user_id != owner_id:
        raise ValueError("There is no current invitation for this server.")
    claim.status = "declined"
    await session.flush()


async def review_claim(
    session: AsyncSession, guild_id: str, approver_id: str, approve: bool,
) -> LeagueClaim:
    claim = await session.get(LeagueClaim, guild_id)
    if claim is None or claim.status != "pending":
        raise ValueError("This League claim is no longer pending.")
    if approve:
        other = await approved_for_league(session, claim.league_id)
        if other is not None and other.guild_id != guild_id:
            raise ValueError("This League is already verified to another Discord server.")
        existing = await session.scalar(
            select(LeagueClaim).where(
                LeagueClaim.guild_id == guild_id,
                LeagueClaim.status == "approved",
            )
        )
        if existing is not None:
            raise ValueError("This server already has a verified League.")
    claim.status = "approved" if approve else "rejected"
    claim.reviewed_by_user_id = approver_id
    claim.reviewed_at = utcnow()
    await session.flush()
    return claim


async def release_claim(
    session: AsyncSession, guild_id: str,
) -> LeagueClaim | None:
    claim = await session.get(LeagueClaim, guild_id)
    if claim is None or claim.status not in ACTIVE_CLAIM_STATES:
        return None
    claim.status = "released"
    await session.flush()
    return claim


async def owned_event(
    session: AsyncSession, guild_id: str, event_id: str,
) -> Event:
    """Recheck approved ownership on every mutation, never trust a UI selector."""
    claim = await session.get(LeagueClaim, guild_id)
    event = await session.get(Event, event_id)
    if (
        claim is None
        or claim.status != "approved"
        or event is None
        or event.source == "community"
        or event.upstream_organisation_id != claim.league_id
    ):
        raise ValueError("This server is not verified to manage that event.")
    return event


async def change_event(
    session: AsyncSession,
    guild_id: str,
    event_id: str,
    user_id: str,
    **changes: object,
) -> Event:
    if not changes or set(changes) - EDITABLE_FIELDS:
        raise ValueError("No supported changes were supplied.")
    event = await owned_event(session, guild_id, event_id)
    if "status" in changes and changes["status"] not in ("active", "cancelled"):
        raise ValueError("Status must be active or cancelled.")
    for name in ("title", "venue_name"):
        if name in changes:
            value = changes[name]
            maximum = 500 if name == "title" else 255
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ValueError(f"Invalid {name}.")
            changes[name] = value.strip()
    if "starts_at" in changes:
        value = changes["starts_at"]
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("Start time must include timezone information.")
        changes["starts_at"] = value.astimezone(UTC)

    override = await session.get(ManualEventOverride, event_id)
    if override is None:
        override = ManualEventOverride(
            event_id=event_id, league_id=event.upstream_organisation_id,
            updated_by_user_id=user_id,
        )
        session.add(override)
    elif override.league_id != event.upstream_organisation_id:
        raise ValueError("Event League does not match its existing override.")

    if "starts_at" in changes and event.ends_at is not None:
        old_start = event.starts_at
        old_end = event.ends_at
        if old_start.tzinfo is None:
            old_start = old_start.replace(tzinfo=UTC)
        if old_end.tzinfo is None:
            old_end = old_end.replace(tzinfo=UTC)
        event.ends_at = old_end + (changes["starts_at"] - old_start)
        override.ends_at = event.ends_at

    for name, value in changes.items():
        setattr(event, name, value)
        setattr(override, name, value)
    override.updated_by_user_id = user_id
    override.updated_at = utcnow()

    organisation_name = None
    if event.organisation_id:
        organisation = await session.get(Organisation, event.organisation_id)
        if organisation is not None:
            organisation_name = organisation.name

    snapshot = EventSnapshot(
        source=event.source,
        upstream_event_id=event.upstream_event_id,
        upstream_organisation_id=event.upstream_organisation_id,
        upstream_location_id=event.upstream_location_id,
        title=event.title,
        game=event.game,
        event_type=event.event_type,
        status=event.status,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        organisation_name=organisation_name,
        venue_name=event.venue_name,
        address=event.address,
        city=event.city,
        postcode=event.postcode,
        country=event.country,
        latitude=event.latitude,
        longitude=event.longitude,
        source_url=event.source_url,
        registration_url=event.registration_url,
    )
    event.content_hash = event_content_hash(snapshot)
    await session.flush()
    return event


async def remove_override(
    session: AsyncSession, guild_id: str, event_id: str,
) -> bool:
    await owned_event(session, guild_id, event_id)
    record = await session.get(ManualEventOverride, event_id)
    if record is None:
        return False
    await session.delete(record)
    await session.flush()
    return True


async def apply_manual_snapshots(
    session: AsyncSession, snapshots: list[EventSnapshot],
) -> list[EventSnapshot]:
    """Apply manually approved corrections last, after any optional feed."""
    if not snapshots:
        return snapshots
    ids = {row.upstream_event_id for row in snapshots}
    events = (
        await session.scalars(
            select(Event).where(Event.upstream_event_id.in_(ids))
        )
    ).all()
    key_by_id = {
        (event.source, event.upstream_event_id): event.id for event in events
    }
    records = (
        await session.scalars(
            select(ManualEventOverride).where(
                ManualEventOverride.event_id.in_(key_by_id.values())
            )
        )
    ).all() if key_by_id else []
    overrides = {row.event_id: row for row in records}
    result = []
    for snapshot in snapshots:
        event_id = key_by_id.get((snapshot.source, snapshot.upstream_event_id))
        row = overrides.get(event_id)
        if row is None or row.league_id != snapshot.upstream_organisation_id:
            result.append(snapshot)
            continue
        changes = {
            field: getattr(row, field)
            for field in ALLOWED_FIELDS
            if getattr(row, field) is not None
        }
        if "status" in changes:
            changes["status"] = EventStatus(changes["status"])
        result.append(snapshot.model_copy(update=changes))
    return result

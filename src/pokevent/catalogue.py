from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .domain import EventSnapshot, EventStatus
from .models import Event, Organisation, utcnow


@dataclass(slots=True)
class CatalogueSyncResult:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    pending_missing: int = 0
    unlisted: int = 0


def event_content_hash(snapshot: EventSnapshot) -> str:
    payload = snapshot.model_dump(
        mode="json",
        exclude={"upstream_payload"},
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def _organisation_for(
    session: AsyncSession,
    snapshot: EventSnapshot,
) -> Organisation | None:
    upstream_id = snapshot.upstream_organisation_id
    if not upstream_id:
        return None

    organisation = await session.scalar(
        select(Organisation).where(
            Organisation.source == "play_pokemon",
            Organisation.upstream_id == upstream_id,
        )
    )
    if organisation is None:
        organisation = Organisation(
            source="play_pokemon",
            upstream_id=upstream_id,
            name=snapshot.organisation_name or snapshot.venue_name or upstream_id,
            kind="league",
        )
        session.add(organisation)
        await session.flush()
    elif snapshot.organisation_name and organisation.name != snapshot.organisation_name:
        organisation.name = snapshot.organisation_name

    return organisation


def _apply_snapshot(
    event: Event,
    snapshot: EventSnapshot,
    *,
    organisation: Organisation | None,
    content_hash: str,
) -> None:
    event.organisation_id = organisation.id if organisation else None
    event.upstream_organisation_id = snapshot.upstream_organisation_id
    event.upstream_location_id = snapshot.upstream_location_id
    event.title = snapshot.title
    event.game = snapshot.game.value if snapshot.game else None
    event.event_type = snapshot.event_type
    event.status = snapshot.status.value
    event.starts_at = snapshot.starts_at
    event.ends_at = snapshot.ends_at
    event.venue_name = snapshot.venue_name
    event.address = snapshot.address
    event.city = snapshot.city
    event.postcode = snapshot.postcode
    event.country = snapshot.country
    event.latitude = snapshot.latitude
    event.longitude = snapshot.longitude
    event.source_url = snapshot.source_url
    event.registration_url = snapshot.registration_url
    event.upstream_payload = snapshot.upstream_payload
    event.content_hash = content_hash
    event.last_seen_at = utcnow()
    event.missing_syncs = 0


async def upsert_snapshots(
    session: AsyncSession,
    snapshots: list[EventSnapshot],
) -> CatalogueSyncResult:
    result = CatalogueSyncResult(fetched=len(snapshots))

    for snapshot in snapshots:
        content_hash = event_content_hash(snapshot)
        event = await session.scalar(
            select(Event).where(
                Event.source == snapshot.source,
                Event.upstream_event_id == snapshot.upstream_event_id,
            )
        )
        organisation = await _organisation_for(session, snapshot)

        if event is None:
            event = Event(
                source=snapshot.source,
                upstream_event_id=snapshot.upstream_event_id,
                title=snapshot.title,
                starts_at=snapshot.starts_at,
                content_hash=content_hash,
            )
            _apply_snapshot(
                event,
                snapshot,
                organisation=organisation,
                content_hash=content_hash,
            )
            session.add(event)
            result.created += 1
            continue

        if event.content_hash == content_hash and event.status == snapshot.status.value:
            event.missing_syncs = 0
            event.last_seen_at = utcnow()
            result.unchanged += 1
            continue

        _apply_snapshot(
            event,
            snapshot,
            organisation=organisation,
            content_hash=content_hash,
        )
        result.updated += 1

    await session.commit()
    return result


async def reconcile_missing_events(
    session: AsyncSession,
    *,
    source: str,
    raw_event_ids: set[str],
    window_start: datetime,
    window_end: datetime,
    country_code: str,
    confirmation_syncs: int = 2,
) -> tuple[int, int]:
    """Confirm upstream omissions without falsely calling them cancellations.

    Compare with every GUID from the complete source country/date feed, before
    local radius and League filtering. Empty feeds are never reconciled.
    """
    if confirmation_syncs < 2:
        raise ValueError("Missing events must be confirmed by at least two syncs")
    if not raw_event_ids:
        return 0, 0

    events = list(
        (
            await session.scalars(
                select(Event).where(
                    Event.source == source,
                    Event.country == country_code,
                    Event.starts_at >= window_start,
                    Event.starts_at < window_end,
                    Event.status.in_(
                        [EventStatus.ACTIVE.value, EventStatus.UNLISTED.value]
                    ),
                )
            )
        ).all()
    )
    pending = 0
    unlisted = 0
    for event in events:
        if event.upstream_event_id in raw_event_ids:
            event.missing_syncs = 0
            continue
        if event.status == EventStatus.UNLISTED.value:
            continue

        event.missing_syncs += 1
        if event.missing_syncs < confirmation_syncs:
            pending += 1
            continue

        event.status = EventStatus.UNLISTED.value
        # Force previously-published Discord cards to be edited.
        # On reappearance, upsert_snapshots restores even unchanged payloads.
        event.content_hash = hashlib.sha256(
            f"unlisted:{event.content_hash}".encode()
        ).hexdigest()
        unlisted += 1

    return pending, unlisted

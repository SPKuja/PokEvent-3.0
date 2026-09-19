from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .domain import EventSnapshot
from .models import Event, Organisation, utcnow


@dataclass(slots=True)
class CatalogueSyncResult:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0


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

        if event.content_hash == content_hash:
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

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from icalendar import Calendar
from icalendar import Event as CalendarEvent
from sqlalchemy import select, text

from . import __version__
from .config import get_settings
from .db import SessionFactory
from .models import Event, Organisation
from .public_site import public_index_html

settings = get_settings()
app = FastAPI(title="PokÈvent", version=__version__)


@app.get("/health")
async def health() -> dict[str, str]:
    async with SessionFactory() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}


def _safe_public_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _public_logo_url(league_id: str | None) -> str | None:
    if not league_id:
        return None
    return _safe_public_url(settings.league_logos.get(league_id))


def _public_event_payload(
    event: Event,
    organisation_name: str | None,
) -> dict:
    league_id = event.upstream_organisation_id
    league_name = (
        settings.leagues.get(league_id or "")
        or organisation_name
        or event.venue_name
        or "Play! Pokémon"
    )
    return {
        "id": event.id,
        "title": event.title,
        "game": event.game,
        "event_type": event.event_type,
        "status": event.status,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "league_id": league_id,
        "league_name": league_name,
        "league_logo": _public_logo_url(league_id),
        "venue_name": event.venue_name,
        "address": event.address,
        "city": event.city,
        "postcode": event.postcode,
        "latitude": event.latitude,
        "longitude": event.longitude,
        "source_url": event.source_url,
        "registration_url": event.registration_url,
    }


@app.get("/", response_class=HTMLResponse)
async def public_calendar() -> HTMLResponse:
    return HTMLResponse(
        public_index_html(
            community_name=settings.community_name,
            brand_logo_url=_safe_public_url(settings.brand_logo_url) or "",
        )
    )


@app.get("/api/events")
async def upcoming_events(
    limit: int = 100,
    include_cancelled: bool = False,
    configured_only: bool = True,
) -> list[dict]:
    now = datetime.now(UTC)
    statuses = ["active", "cancelled"] if include_cancelled else ["active"]
    filters = [
        Event.starts_at >= now,
        Event.status.in_(statuses),
    ]

    if configured_only:
        league_ids = list(settings.leagues)
        if not league_ids:
            return []
        filters.append(Event.upstream_organisation_id.in_(league_ids))

    async with SessionFactory() as session:
        rows = (
            await session.execute(
                select(Event, Organisation.name)
                .outerjoin(Organisation, Event.organisation_id == Organisation.id)
                .where(*filters)
                .order_by(Event.starts_at)
                .limit(min(max(limit, 1), 500))
            )
        ).all()

    return [
        _public_event_payload(event, organisation_name)
        for event, organisation_name in rows
    ]


def _calendar_event(event: Event) -> CalendarEvent:
    item = CalendarEvent()
    item.add("uid", f"{event.id}@pokevent")
    item.add("summary", event.title)
    item.add("dtstart", event.starts_at)
    if event.ends_at:
        item.add("dtend", event.ends_at)
    if event.address or event.venue_name:
        item.add(
            "location",
            ", ".join(part for part in (event.venue_name, event.address) if part),
        )
    if event.source_url:
        item.add("url", event.source_url)
    return item


@app.get("/events/{event_id}.ics")
async def event_calendar_file(event_id: str) -> Response:
    async with SessionFactory() as session:
        event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    calendar = Calendar()
    calendar.add("prodid", "-//PokÈvent 3.0//EN")
    calendar.add("version", "2.0")
    calendar.add_component(_calendar_event(event))
    return Response(
        content=calendar.to_ical(),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="pokevent-{event.id}.ics"'},
    )


@app.get("/calendar.ics")
async def calendar_feed(configured_only: bool = True) -> Response:
    now = datetime.now(UTC)
    filters = [
        Event.starts_at >= now,
        Event.status == "active",
    ]
    if configured_only:
        league_ids = list(settings.leagues)
        if not league_ids:
            league_ids = ["__none__"]
        filters.append(Event.upstream_organisation_id.in_(league_ids))

    async with SessionFactory() as session:
        rows = (
            await session.scalars(
                select(Event)
                .where(*filters)
                .order_by(Event.starts_at)
            )
        ).all()

    calendar = Calendar()
    calendar.add("prodid", "-//PokÈvent 3.0//EN")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", f"{settings.community_name} Events")

    for event in rows:
        calendar.add_component(_calendar_event(event))

    return Response(
        content=calendar.to_ical(),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="pokevent.ics"'},
    )


def main() -> None:
    uvicorn.run("pokevent.web:app", host="0.0.0.0", port=8080, reload=False)

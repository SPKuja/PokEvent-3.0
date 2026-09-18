from __future__ import annotations

from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Response
from icalendar import Calendar, Event as CalendarEvent
from sqlalchemy import select

from . import __version__
from .config import get_settings
from .db import SessionFactory, initialise_database
from .models import Event

settings = get_settings()
app = FastAPI(title="PokEvent", version=__version__)


@app.on_event("startup")
async def startup() -> None:
    await initialise_database()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/events")
async def upcoming_events(limit: int = 100) -> list[dict]:
    now = datetime.now(timezone.utc)
    async with SessionFactory() as session:
        rows = (
            await session.scalars(
                select(Event)
                .where(Event.starts_at >= now, Event.status == "active")
                .order_by(Event.starts_at)
                .limit(min(max(limit, 1), 500))
            )
        ).all()

    return [
        {
            "id": event.id,
            "title": event.title,
            "game": event.game,
            "event_type": event.event_type,
            "starts_at": event.starts_at,
            "venue_name": event.venue_name,
            "city": event.city,
            "source_url": event.source_url,
        }
        for event in rows
    ]


@app.get("/calendar.ics")
async def calendar_feed() -> Response:
    now = datetime.now(timezone.utc)
    async with SessionFactory() as session:
        rows = (
            await session.scalars(
                select(Event)
                .where(Event.starts_at >= now, Event.status == "active")
                .order_by(Event.starts_at)
            )
        ).all()

    calendar = Calendar()
    calendar.add("prodid", "-//PokEvent 3.0//EN")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", f"{settings.community_name} Events")

    for event in rows:
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
        calendar.add_component(item)

    return Response(
        content=calendar.to_ical(),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="pokevent.ics"'},
    )


def main() -> None:
    uvicorn.run("pokevent.web:app", host="0.0.0.0", port=8080, reload=False)

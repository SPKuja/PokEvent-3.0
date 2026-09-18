from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from .catalogue import upsert_snapshots
from .config import get_settings
from .db import SessionFactory
from .domain import EventSearch
from .sources.pokedata import PokedataSource

log = logging.getLogger("pokevent.worker")
settings = get_settings()


def build_source() -> PokedataSource:
    if settings.event_source == "pokedata":
        return PokedataSource()
    raise RuntimeError(f"Unsupported POKEVENT_EVENT_SOURCE: {settings.event_source}")


async def sync_once() -> None:
    source = build_source()
    search = EventSearch(
        latitude=settings.home_latitude,
        longitude=settings.home_longitude,
        radius_miles=settings.default_radius_miles,
        starts_after=datetime.now(UTC),
    )
    snapshots = await source.fetch_events(search)

    async with SessionFactory() as session:
        result = await upsert_snapshots(session, snapshots)

    log.info(
        "sync complete source=%s fetched=%s created=%s updated=%s unchanged=%s",
        source.name,
        result.fetched,
        result.created,
        result.updated,
        result.unchanged,
    )


async def run_worker() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    while True:
        try:
            await sync_once()
        except Exception:
            log.exception("event sync failed; cached catalogue left intact")

        await asyncio.sleep(settings.sync_interval_minutes * 60)


def main() -> None:
    asyncio.run(run_worker())

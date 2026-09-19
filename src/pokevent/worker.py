from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from .catalogue import upsert_snapshots
from .config import get_settings
from .db import SessionFactory
from .domain import EventSearch, EventSnapshot
from .guild_config import all_monitored_league_ids, baseline_pending_routes
from .sources.pokedata import PokedataSource

log = logging.getLogger("pokevent.worker")
settings = get_settings()


def build_source(monitored_league_ids: set[str]) -> PokedataSource:
    if settings.event_source == "pokedata":
        return PokedataSource(
            country_code=settings.country_code,
            local_timezone=settings.local_timezone,
            horizon_days=settings.event_horizon_days,
            monitored_league_ids=monitored_league_ids,
        )
    raise RuntimeError(f"Unsupported POKEVENT_EVENT_SOURCE: {settings.event_source}")


def apply_league_registry(snapshot: EventSnapshot) -> EventSnapshot:
    league_id = snapshot.upstream_organisation_id
    if not league_id:
        return snapshot

    configured_name = settings.leagues.get(league_id)
    if not configured_name:
        return snapshot

    return snapshot.model_copy(update={"organisation_name": configured_name})


async def sync_once() -> None:
    async with SessionFactory() as session:
        monitored_ids = await all_monitored_league_ids(
            session,
            settings.leagues.keys(),
        )

    source = build_source(monitored_ids)
    search = EventSearch(
        latitude=settings.home_latitude,
        longitude=settings.home_longitude,
        radius_miles=settings.default_radius_miles,
        starts_after=datetime.now(UTC),
    )
    snapshots = [
        apply_league_registry(snapshot)
        for snapshot in await source.fetch_events(search)
    ]

    async with SessionFactory() as session:
        result = await upsert_snapshots(session, snapshots)
        baselined = await baseline_pending_routes(session)
        await session.commit()

    log.info(
        "sync complete source=%s fetched=%s created=%s updated=%s unchanged=%s "
        "routes_baselined=%s",
        source.name,
        result.fetched,
        result.created,
        result.updated,
        result.unchanged,
        baselined,
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

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pokevent.catalogue import upsert_snapshots
from pokevent.domain import EventSnapshot, Game
from pokevent.models import Base, Event, Organisation


@pytest.mark.asyncio
async def test_catalogue_creates_league_and_updates_same_event() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    original = EventSnapshot(
        source="pokedata",
        upstream_event_id="event-guid-1",
        upstream_organisation_id="2012924",
        organisation_name="POKEMON LEAGUE SWINDON",
        title="League Challenge",
        game=Game.TCG,
        event_type="League Challenge",
        starts_at=datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
        latitude=51.5615,
        longitude=-1.7855,
    )

    async with sessions() as session:
        first = await upsert_snapshots(session, [original])

    assert first.created == 1

    changed = original.model_copy(update={"title": "League Challenge - Updated"})
    async with sessions() as session:
        second = await upsert_snapshots(session, [changed])
        stored_event = await session.scalar(select(Event))
        stored_league = await session.scalar(select(Organisation))

    assert second.updated == 1
    assert stored_event is not None
    assert stored_event.title == "League Challenge - Updated"
    assert stored_event.upstream_organisation_id == "2012924"
    assert stored_league is not None
    assert stored_league.source == "play_pokemon"
    assert stored_league.upstream_id == "2012924"

    await engine.dispose()

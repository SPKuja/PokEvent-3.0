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


@pytest.mark.asyncio
async def test_missing_events_confirmed_then_reappear_without_duplicate() -> None:
    from pokevent.catalogue import reconcile_missing_events
    from pokevent.domain import EventStatus

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    def snapshot(guid: str, status: EventStatus = EventStatus.ACTIVE) -> EventSnapshot:
        return EventSnapshot(
            source="pokedata",
            upstream_event_id=guid,
            upstream_organisation_id="2012924",
            title=guid,
            status=status,
            game=Game.TCG,
            event_type="Friendly Tournament",
            starts_at=datetime(2026, 10, 18, 10, tzinfo=UTC),
            country="GB",
        )

    friendly = snapshot("old-friendly")
    challenge = snapshot("new-challenge")
    cancelled = snapshot("explicit-cancellation", EventStatus.CANCELLED)
    current_ids = {"new-challenge", "explicit-cancellation"}
    kwargs = {
        "source": "pokedata",
        "raw_event_ids": current_ids,
        "window_start": datetime(2026, 10, 10, tzinfo=UTC),
        "window_end": datetime(2026, 11, 1, tzinfo=UTC),
        "country_code": "GB",
    }

    async with sessions() as session:
        await upsert_snapshots(session, [friendly, challenge, cancelled])
        event = await session.scalar(
            select(Event).where(Event.upstream_event_id == "old-friendly")
        )
        assert event is not None
        prior_hash = event.content_hash

        first = await reconcile_missing_events(session, **kwargs)
        await session.commit()
        assert first == (1, 0)
        assert event.status == "active"
        assert event.missing_syncs == 1

        second = await reconcile_missing_events(session, **kwargs)
        await session.commit()
        assert second == (0, 1)
        assert event.status == "unlisted"
        assert event.content_hash != prior_hash
        assert event.missing_syncs == 2

        third = await reconcile_missing_events(session, **kwargs)
        await session.commit()
        assert third == (0, 0)

        explicitly_cancelled = await session.scalar(
            select(Event).where(Event.upstream_event_id == "explicit-cancellation")
        )
        assert explicitly_cancelled is not None
        assert explicitly_cancelled.status == "cancelled"

        # Reappearing source data returns an unlisted event to active, even
        # if its original source content hash has not changed.
        restored = await upsert_snapshots(session, [friendly])
        assert restored.updated == 1
        assert event.status == "active"
        assert event.content_hash == prior_hash
        assert event.missing_syncs == 0

        # A single later omission must not immediately hide a returned event.
        assert await reconcile_missing_events(session, **kwargs) == (1, 0)
        assert event.status == "active"

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_ignores_empty_feed_outside_window_and_country() -> None:
    from pokevent.catalogue import reconcile_missing_events

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    event_in_other_country = EventSnapshot(
        source="pokedata",
        upstream_event_id="other-country",
        title="Other",
        starts_at=datetime(2026, 10, 18, 10, tzinfo=UTC),
        country="FR",
    )
    event_in_future = EventSnapshot(
        source="pokedata",
        upstream_event_id="future",
        title="Future",
        starts_at=datetime(2027, 1, 18, 10, tzinfo=UTC),
        country="GB",
    )
    async with sessions() as session:
        await upsert_snapshots(session, [event_in_other_country, event_in_future])
        for source_ids in (set(), {"unrelated-guid"}):
            for _ in range(3):
                assert await reconcile_missing_events(
                    session,
                    source="pokedata",
                    raw_event_ids=source_ids,
                    window_start=datetime(2026, 10, 10, tzinfo=UTC),
                    window_end=datetime(2026, 11, 1, tzinfo=UTC),
                    country_code="GB",
                ) == (0, 0)
        events = list((await session.scalars(select(Event))).all())
        assert len(events) == 2
        assert all(event.status == "active" and event.missing_syncs == 0
                   for event in events)

    await engine.dispose()

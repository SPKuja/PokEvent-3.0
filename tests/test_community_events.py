from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pokevent.community_events import (
    cancel_community_event,
    create_community_event,
    parse_local_datetime,
    update_community_event_core,
    update_community_event_details,
)
from pokevent.discord_bot import _guild_visible_event_clause
from pokevent.models import Base, Event


@pytest.mark.asyncio
async def test_community_event_lifecycle_is_guild_owned_and_private() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        event = await create_community_event(
            session,
            guild_id="guild-1",
            creator_user_id="user-1",
            league_id="2012924",
            title="Gym Leader Challenge Night",
            starts_at=datetime(2026, 10, 2, 18, 0, tzinfo=UTC),
            game="TCG",
            event_type="Friendly Tournament",
            venue_name="Example Venue",
        )
        event_id = event.id
        original_hash = event.content_hash
        await session.commit()

    async with sessions() as session:
        stored = await session.get(Event, event_id)
        assert stored is not None
        assert stored.source == "community"
        assert stored.owner_guild_id == "guild-1"
        assert stored.created_by_user_id == "user-1"
        assert stored.public_visible is False
        assert stored.upstream_organisation_id == "2012924"
        assert stored.game == "tcg"

        updated = await update_community_event_details(
            session,
            guild_id="guild-1",
            event_id=event_id,
            ends_at=datetime(2026, 10, 2, 21, 0, tzinfo=UTC),
            address="1 Example Street",
            description="Bring a legal GLC deck.",
            registration_url="https://example.com/register",
        )
        assert updated.content_hash != original_hash
        updated_hash = updated.content_hash
        await session.commit()

    async with sessions() as session:
        updated = await update_community_event_core(
            session,
            guild_id="guild-1",
            event_id=event_id,
            title="Updated GLC Night",
            starts_at=datetime(2026, 10, 2, 18, 30, tzinfo=UTC),
            game="tcg",
            event_type="Community Event",
            venue_name="Updated Venue",
        )
        assert updated.content_hash != updated_hash
        await session.commit()

    async with sessions() as session:
        cancelled = await cancel_community_event(
            session,
            guild_id="guild-1",
            event_id=event_id,
        )
        assert cancelled.status == "cancelled"
        await session.commit()

    async with sessions() as session:
        with pytest.raises(ValueError, match="does not belong"):
            await cancel_community_event(
                session,
                guild_id="guild-2",
                event_id=event_id,
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_guild_visibility_clause_hides_other_servers_community_events() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    official = Event(
        source="pokedata",
        upstream_event_id="official-1",
        upstream_organisation_id="2012924",
        title="Official Event",
        starts_at=datetime(2026, 10, 10, 10, 0, tzinfo=UTC),
        content_hash="official",
    )
    own = Event(
        source="community",
        upstream_event_id="community-1",
        owner_guild_id="guild-1",
        public_visible=False,
        upstream_organisation_id="2012924",
        title="Own Community Event",
        starts_at=datetime(2026, 10, 10, 11, 0, tzinfo=UTC),
        content_hash="own",
    )
    other = Event(
        source="community",
        upstream_event_id="community-2",
        owner_guild_id="guild-2",
        public_visible=False,
        upstream_organisation_id="2012924",
        title="Other Community Event",
        starts_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
        content_hash="other",
    )

    async with sessions() as session:
        session.add_all([official, own, other])
        await session.commit()

    async with sessions() as session:
        rows = list(
            (
                await session.scalars(
                    select(Event)
                    .where(_guild_visible_event_clause("guild-1"))
                    .order_by(Event.starts_at)
                )
            ).all()
        )

    assert [event.title for event in rows] == [
        "Official Event",
        "Own Community Event",
    ]
    await engine.dispose()


def test_community_datetime_parser_uses_configured_local_timezone() -> None:
    parsed = parse_local_datetime("2026-10-02 19:00", "Europe/London")

    assert parsed == datetime(2026, 10, 2, 18, 0, tzinfo=UTC)

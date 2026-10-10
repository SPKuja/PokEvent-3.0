from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pokevent.catalogue import upsert_snapshots
from pokevent.domain import EventSnapshot
from pokevent.league_claims import (
    apply_manual_snapshots,
    approved_for_league,
    change_event,
    decline_invitation,
    invite_server_owner,
    owned_event,
    release_claim,
    remove_override,
    request_claim,
    review_claim,
)
from pokevent.models import Base, Event, GuildConfig, LeagueClaim, ManualEventOverride

SWINDON = "2012924"
BATH = "5683200"


@pytest.fixture
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()


def swindon_event() -> EventSnapshot:
    return EventSnapshot(
        source="pokedata", upstream_event_id="event-1",
        upstream_organisation_id=SWINDON,
        title="Swindon Friendly", status="active",
        starts_at=datetime(2026, 10, 18, 11, tzinfo=UTC),
        country="GB",
    )


@pytest.mark.asyncio
async def test_existing_server_owner_invited_once_and_can_decline(sessions) -> None:
    async with sessions() as session:
        session.add(GuildConfig(guild_id="guild-a", default_league_id=SWINDON))
        await session.commit()
        assert await invite_server_owner(session, "guild-a", SWINDON, "owner-a")
        assert not await invite_server_owner(session, "guild-a", SWINDON, "owner-a")
        await decline_invitation(session, "guild-a", "owner-a")
        await session.commit()
        assert not await invite_server_owner(session, "guild-a", SWINDON, "owner-a")
        claim = await session.get(LeagueClaim, "guild-a")
        assert claim.status == "declined"
        assert await approved_for_league(session, SWINDON) is None


@pytest.mark.asyncio
async def test_pending_claim_requires_review_and_competitors_cannot_claim(sessions) -> None:
    async with sessions() as session:
        session.add(GuildConfig(guild_id="guild-a", default_league_id=SWINDON))
        session.add(GuildConfig(guild_id="guild-b", default_league_id=SWINDON))
        await session.commit()

        request = await request_claim(session, "guild-a", "owner-a")
        assert request.status == "pending"
        with pytest.raises(ValueError, match="awaiting approval"):
            await request_claim(session, "guild-a", "owner-a")
        assert await approved_for_league(session, SWINDON) is None
        claim = await review_claim(session, "guild-a", "pokevent-owner", True)
        await session.commit()
        assert claim.status == "approved"
        assert claim.reviewed_by_user_id == "pokevent-owner"

        with pytest.raises(ValueError, match="already claimed"):
            await request_claim(session, "guild-b", "owner-b")
        with pytest.raises(ValueError, match="already has a verified"):
            await request_claim(session, "guild-a", "owner-a")
        assert not await invite_server_owner(session, "guild-b", SWINDON, "owner-b")

        await release_claim(session, "guild-a")
        await session.commit()
        new = await request_claim(session, "guild-b", "owner-b")
        assert new.status == "pending"


@pytest.mark.asyncio
async def test_one_server_cannot_claim_two_leagues(sessions) -> None:
    async with sessions() as session:
        config = GuildConfig(guild_id="guild-a", default_league_id=SWINDON)
        session.add(config)
        await session.commit()
        await request_claim(session, "guild-a", "owner-a")
        await review_claim(session, "guild-a", "pokevent-owner", True)
        await session.commit()
        config.default_league_id = BATH
        await session.commit()
        with pytest.raises(ValueError, match="already has a verified"):
            await request_claim(session, "guild-a", "owner-a")


@pytest.mark.asyncio
async def test_manual_override_is_league_scoped_and_survives_pokedata(sessions) -> None:
    snapshot = swindon_event()
    async with sessions() as session:
        session.add(GuildConfig(guild_id="guild-a", default_league_id=SWINDON))
        session.add(GuildConfig(guild_id="guild-b", default_league_id=BATH))
        await session.commit()
        await request_claim(session, "guild-a", "owner-a")
        await review_claim(session, "guild-a", "pokevent-owner", True)
        await session.commit()
        await upsert_snapshots(session, [snapshot])

        event = await session.get(Event, (
            await session.scalar(__import__("sqlalchemy").select(Event.id))
        ))
        assert event.status == "active"
        with pytest.raises(ValueError, match="not verified"):
            await change_event(
                session, "guild-b", event.id, "admin-b", status="cancelled"
            )
        await change_event(
            session, "guild-a", event.id, "admin-a",
            status="cancelled", venue_name="The Incredible Comic Shop",
        )
        await session.commit()
        assert (await session.get(ManualEventOverride, event.id)).status == "cancelled"

        corrected = (await apply_manual_snapshots(session, [snapshot]))[0]
        assert corrected.status == "cancelled"
        assert corrected.venue_name == "The Incredible Comic Shop"
        await upsert_snapshots(session, [corrected])
        assert (await session.get(Event, event.id)).status == "cancelled"

        assert await remove_override(session, "guild-a", event.id)
        await session.commit()
        restored = (await apply_manual_snapshots(session, [snapshot]))[0]
        assert restored.status == "active"
        await upsert_snapshots(session, [restored])
        assert (await session.get(Event, event.id)).status == "active"


@pytest.mark.asyncio
async def test_unclaimed_server_cannot_edit_any_event(sessions) -> None:
    async with sessions() as session:
        session.add(GuildConfig(guild_id="guild-a", default_league_id=SWINDON))
        await session.commit()
        await upsert_snapshots(session, [swindon_event()])
        event = await session.get(Event, await session.scalar(__import__("sqlalchemy").select(Event.id)))
        with pytest.raises(ValueError, match="not verified"):
            await owned_event(session, "guild-a", event.id)

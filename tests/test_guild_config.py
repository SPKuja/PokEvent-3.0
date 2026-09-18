import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pokevent import guild_config
from pokevent.guild_config import (
    add_guild_league,
    clear_event_channel,
    ensure_guild_config,
    guild_leagues,
    remove_guild_league,
    set_default_league,
    set_event_channel,
)
from pokevent.models import Base, GuildConfig, Route


@pytest.mark.asyncio
async def test_guild_league_channels_follow_default_specific_all_precedence(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        guild_config.settings,
        "leagues",
        {
            "2012924": "Pokémon League Swindon",
            "5683200": "Bath TCG",
        },
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        await ensure_guild_config(session, "guild-1")
        await set_default_league(session, "guild-1", "Pokémon League Swindon")
        await set_event_channel(session, "guild-1", "default", "100")
        await set_event_channel(session, "guild-1", "all", "200")
        await session.commit()

    async with sessions() as session:
        routes = {
            route.upstream_organisation_id: route
            for route in (
                await session.scalars(
                    select(Route).where(Route.guild_id == "guild-1")
                )
            ).all()
        }

    assert routes["2012924"].channel_id == "100"
    assert routes["2012924"].enabled is True
    assert routes["5683200"].channel_id == "200"
    assert routes["5683200"].enabled is True

    async with sessions() as session:
        await set_event_channel(session, "guild-1", "Bath TCG", "300")
        added = await add_guild_league(
            session,
            "guild-1",
            "Another League",
            "9999999",
        )
        await session.commit()
        assert added.channel_id is None

    async with sessions() as session:
        routes = {
            route.upstream_organisation_id: route
            for route in (
                await session.scalars(
                    select(Route).where(Route.guild_id == "guild-1")
                )
            ).all()
        }

    assert routes["5683200"].channel_id == "300"
    assert routes["9999999"].channel_id == "200"

    async with sessions() as session:
        await clear_event_channel(session, "guild-1", "Bath TCG")
        await session.commit()

    async with sessions() as session:
        bath_route = await session.scalar(
            select(Route).where(
                Route.guild_id == "guild-1",
                Route.upstream_organisation_id == "5683200",
            )
        )
        assert bath_route is not None
        assert bath_route.channel_id == "200"

    await engine.dispose()


@pytest.mark.asyncio
async def test_removing_default_league_clears_default(monkeypatch) -> None:
    monkeypatch.setattr(
        guild_config.settings,
        "leagues",
        {"2012924": "Pokémon League Swindon"},
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        await ensure_guild_config(session, "guild-1")
        await set_default_league(session, "guild-1", "Pokémon League Swindon")
        await set_event_channel(session, "guild-1", "default", "100")
        await remove_guild_league(
            session,
            "guild-1",
            "Pokémon League Swindon",
        )
        await session.commit()

    async with sessions() as session:
        config = await session.get(GuildConfig, "guild-1")
        leagues = await guild_leagues(session, "guild-1")
        route = await session.scalar(
            select(Route).where(Route.guild_id == "guild-1")
        )

    assert config is not None
    assert config.default_league_id is None
    assert config.default_channel_id is None
    assert leagues == []
    assert route is None

    await engine.dispose()

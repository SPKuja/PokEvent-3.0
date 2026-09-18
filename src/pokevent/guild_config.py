from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import GuildConfig, GuildLeague, Route

settings = get_settings()


def league_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


async def ensure_guild_config(
    session: AsyncSession,
    guild_id: str,
) -> GuildConfig:
    config = await session.get(GuildConfig, guild_id)
    if config is None:
        config = GuildConfig(guild_id=guild_id, leagues_seeded=False)
        session.add(config)
        await session.flush()

    if not config.leagues_seeded:
        existing_ids = set(
            (
                await session.scalars(
                    select(GuildLeague.league_id).where(
                        GuildLeague.guild_id == guild_id
                    )
                )
            ).all()
        )
        existing_keys = set(
            (
                await session.scalars(
                    select(GuildLeague.name_key).where(
                        GuildLeague.guild_id == guild_id
                    )
                )
            ).all()
        )

        for league_id, name in settings.leagues.items():
            key = league_key(name)
            if league_id in existing_ids or key in existing_keys:
                continue
            session.add(
                GuildLeague(
                    guild_id=guild_id,
                    name=name,
                    name_key=key,
                    league_id=league_id,
                    origin="service",
                )
            )
            existing_ids.add(league_id)
            existing_keys.add(key)

        config.leagues_seeded = True
        await session.flush()

    return config


async def guild_leagues(
    session: AsyncSession,
    guild_id: str,
) -> list[GuildLeague]:
    await ensure_guild_config(session, guild_id)
    return list(
        (
            await session.scalars(
                select(GuildLeague)
                .where(GuildLeague.guild_id == guild_id)
                .order_by(GuildLeague.name)
            )
        ).all()
    )


async def resolve_guild_league(
    session: AsyncSession,
    guild_id: str,
    selector: str,
) -> GuildLeague | None:
    await ensure_guild_config(session, guild_id)
    key = league_key(selector)

    result = await session.scalar(
        select(GuildLeague).where(
            GuildLeague.guild_id == guild_id,
            GuildLeague.name_key == key,
        )
    )
    if result is not None:
        return result

    return await session.scalar(
        select(GuildLeague).where(
            GuildLeague.guild_id == guild_id,
            GuildLeague.league_id == selector.strip(),
        )
    )


async def add_guild_league(
    session: AsyncSession,
    guild_id: str,
    name: str,
    league_id: str,
) -> GuildLeague:
    await ensure_guild_config(session, guild_id)

    clean_name = re.sub(r"\s+", " ", name.strip())
    clean_id = league_id.strip()
    if not clean_name:
        raise ValueError("League name cannot be empty.")
    if not clean_id:
        raise ValueError("League ID cannot be empty.")

    existing_id = await session.scalar(
        select(GuildLeague).where(
            GuildLeague.guild_id == guild_id,
            GuildLeague.league_id == clean_id,
        )
    )
    if existing_id is not None:
        raise ValueError(
            f"League ID {clean_id} is already configured as {existing_id.name}."
        )

    key = league_key(clean_name)
    existing_name = await session.scalar(
        select(GuildLeague).where(
            GuildLeague.guild_id == guild_id,
            GuildLeague.name_key == key,
        )
    )
    if existing_name is not None:
        raise ValueError(f"A League named {existing_name.name} is already configured.")

    league = GuildLeague(
        guild_id=guild_id,
        name=clean_name,
        name_key=key,
        league_id=clean_id,
        origin="server",
    )
    session.add(league)
    await session.flush()
    await reconcile_guild_routes(session, guild_id)
    return league


async def rename_guild_league(
    session: AsyncSession,
    guild_id: str,
    selector: str,
    new_name: str,
) -> GuildLeague:
    league = await resolve_guild_league(session, guild_id, selector)
    if league is None:
        raise ValueError(f"Unknown League: {selector}")

    clean_name = re.sub(r"\s+", " ", new_name.strip())
    key = league_key(clean_name)
    conflict = await session.scalar(
        select(GuildLeague).where(
            GuildLeague.guild_id == guild_id,
            GuildLeague.name_key == key,
            GuildLeague.id != league.id,
        )
    )
    if conflict is not None:
        raise ValueError(f"A League named {conflict.name} is already configured.")

    league.name = clean_name
    league.name_key = key
    await session.flush()
    return league


async def remove_guild_league(
    session: AsyncSession,
    guild_id: str,
    selector: str,
) -> GuildLeague:
    config = await ensure_guild_config(session, guild_id)
    league = await resolve_guild_league(session, guild_id, selector)
    if league is None:
        raise ValueError(f"Unknown League: {selector}")

    if config.default_league_id == league.league_id:
        config.default_league_id = None
        config.default_channel_id = None

    route = await session.scalar(
        select(Route).where(
            Route.guild_id == guild_id,
            Route.upstream_organisation_id == league.league_id,
        )
    )
    if route is not None:
        await session.delete(route)

    await session.delete(league)
    await session.flush()
    return league


async def set_default_league(
    session: AsyncSession,
    guild_id: str,
    selector: str,
) -> GuildLeague:
    config = await ensure_guild_config(session, guild_id)
    league = await resolve_guild_league(session, guild_id, selector)
    if league is None:
        raise ValueError(f"Unknown League: {selector}")

    config.default_league_id = league.league_id
    await session.flush()
    await reconcile_guild_routes(session, guild_id)
    return league


async def set_event_channel(
    session: AsyncSession,
    guild_id: str,
    target: str,
    channel_id: str,
) -> str:
    config = await ensure_guild_config(session, guild_id)
    key = league_key(target)

    if key == "default":
        if not config.default_league_id:
            raise ValueError("Set a default League before setting its channel.")
        config.default_channel_id = channel_id
        description = "default League"
    elif key == "all":
        config.all_channel_id = channel_id
        description = "all non-default Leagues"
    elif key == "nearby":
        raise ValueError("Nearby events are browse-only and cannot be auto-posted.")
    else:
        league = await resolve_guild_league(session, guild_id, target)
        if league is None:
            raise ValueError(f"Unknown League: {target}")
        if league.league_id == config.default_league_id:
            config.default_channel_id = channel_id
            description = f"default League {league.name}"
        else:
            league.channel_id = channel_id
            description = league.name

    await session.flush()
    await reconcile_guild_routes(session, guild_id)
    return description


async def clear_event_channel(
    session: AsyncSession,
    guild_id: str,
    target: str,
) -> str:
    config = await ensure_guild_config(session, guild_id)
    key = league_key(target)

    if key == "default":
        config.default_channel_id = None
        description = "default League"
    elif key == "all":
        config.all_channel_id = None
        description = "all non-default Leagues"
    elif key == "nearby":
        raise ValueError("Nearby events do not have an auto-post channel.")
    else:
        league = await resolve_guild_league(session, guild_id, target)
        if league is None:
            raise ValueError(f"Unknown League: {target}")
        if league.league_id == config.default_league_id:
            config.default_channel_id = None
            description = f"default League {league.name}"
        else:
            league.channel_id = None
            description = league.name

    await session.flush()
    await reconcile_guild_routes(session, guild_id)
    return description


async def reconcile_guild_routes(
    session: AsyncSession,
    guild_id: str,
) -> None:
    config = await ensure_guild_config(session, guild_id)
    leagues = await guild_leagues(session, guild_id)

    configured_ids = {league.league_id for league in leagues}
    routes = list(
        (
            await session.scalars(
                select(Route).where(Route.guild_id == guild_id)
            )
        ).all()
    )
    route_by_league = {
        route.upstream_organisation_id: route
        for route in routes
        if route.upstream_organisation_id is not None
    }

    for route in routes:
        if (
            route.upstream_organisation_id is not None
            and route.upstream_organisation_id not in configured_ids
        ):
            await session.delete(route)

    for league in leagues:
        if league.league_id == config.default_league_id:
            channel_id = config.default_channel_id
        else:
            channel_id = league.channel_id or config.all_channel_id

        route = route_by_league.get(league.league_id)
        if channel_id is None:
            if route is not None:
                route.enabled = False
            continue

        if route is None:
            route = Route(
                guild_id=guild_id,
                channel_id=channel_id,
                upstream_organisation_id=league.league_id,
                enabled=True,
                announce_new=True,
                announce_updates=True,
            )
            session.add(route)
        else:
            route.channel_id = channel_id
            route.enabled = True

    await session.flush()


async def all_monitored_league_ids(
    session: AsyncSession,
    extra_ids: Iterable[str] = (),
) -> set[str]:
    ids = set(extra_ids)
    ids.update(
        (
            await session.scalars(
                select(GuildLeague.league_id).distinct()
            )
        ).all()
    )
    return ids

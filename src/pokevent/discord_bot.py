from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from . import __version__
from .config import get_settings
from .db import SessionFactory
from .guild_config import (
    add_guild_league,
    clear_event_channel,
    ensure_guild_config,
    guild_leagues,
    remove_guild_league,
    rename_guild_league,
    resolve_event_channel,
    resolve_guild_league,
    set_default_league,
    set_event_channel,
)
from .models import ChannelSummary, Event, GuildLeague, PublishedMessage, Route

settings = get_settings()
log = logging.getLogger("pokevent.discord")

EVENTS_PAGE_SIZE = 10
EVENTS_QUERY_LIMIT = 250


class PokEventBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self._synced_guild_ids: set[int] = set()
        self._global_commands_removed = False

    async def setup_hook(self) -> None:
        if not settings.sync_guild_commands:
            await self.tree.sync()
        if not publish_event_routes.is_running():
            publish_event_routes.start()
        if not cleanup_expired_event_posts.is_running():
            cleanup_expired_event_posts.start()
        if not refresh_channel_summaries.is_running():
            refresh_channel_summaries.start()

    async def _sync_commands_to_guild(self, guild: discord.Guild) -> None:
        if not settings.sync_guild_commands or guild.id in self._synced_guild_ids:
            return

        guild_ref = discord.Object(id=guild.id)
        self.tree.clear_commands(guild=guild_ref)
        self.tree.copy_global_to(guild=guild_ref)
        synced = await self.tree.sync(guild=guild_ref)
        self._synced_guild_ids.add(guild.id)
        log.info(
            "synced %s application commands directly to guild=%s (%s)",
            len(synced),
            guild.id,
            guild.name,
        )

    async def _remove_remote_global_commands(self) -> None:
        if self._global_commands_removed or not settings.sync_guild_commands:
            return

        global_commands = list(self.tree.get_commands())
        self.tree.clear_commands(guild=None)
        await self.tree.sync()

        for command in global_commands:
            self.tree.add_command(command, override=True)

        self._global_commands_removed = True
        log.info("removed global command copies while guild-sync mode is enabled")

    async def on_ready(self) -> None:
        for guild in self.guilds:
            try:
                await self._sync_commands_to_guild(guild)
            except discord.HTTPException:
                log.exception("failed to sync commands to guild=%s", guild.id)

        try:
            await self._remove_remote_global_commands()
        except discord.HTTPException:
            log.exception("failed to remove duplicate global commands")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            await self._sync_commands_to_guild(guild)
        except discord.HTTPException:
            log.exception("failed to sync commands to new guild=%s", guild.id)


def _event_line(event: Event) -> str:
    title = event.title
    if len(title) > 120:
        title = f"{title[:117]}..."
    return f"**{title}** — {discord.utils.format_dt(event.starts_at, style='F')}"


def event_page_content(rows: list[Event], page: int, heading: str) -> str:
    total_pages = max(1, math.ceil(len(rows) / EVENTS_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    start = page * EVENTS_PAGE_SIZE
    visible = rows[start : start + EVENTS_PAGE_SIZE]

    lines = [f"### {heading}"]
    lines.extend(_event_line(event) for event in visible)
    lines.append("")
    lines.append(
        f"Page **{page + 1}/{total_pages}** · "
        f"Showing {start + 1}-{start + len(visible)} of {len(rows)} upcoming events"
    )
    return "\n".join(lines)


class EventPagerView(discord.ui.View):
    def __init__(self, rows: list[Event], heading: str) -> None:
        super().__init__(timeout=180)
        self.rows = rows
        self.heading = heading
        self.page = 0
        self.total_pages = max(1, math.ceil(len(rows) / EVENTS_PAGE_SIZE))
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.previous_page.disabled = self.page <= 0
        self.next_page.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(
        label="Previous",
        style=discord.ButtonStyle.secondary,
        emoji="◀️",
    )
    async def previous_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        if self.page > 0:
            self.page -= 1
        self._sync_buttons()
        await interaction.response.edit_message(
            content=event_page_content(self.rows, self.page, self.heading),
            view=self,
        )

    @discord.ui.button(
        label="Next",
        style=discord.ButtonStyle.secondary,
        emoji="▶️",
    )
    async def next_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        if self.page < self.total_pages - 1:
            self.page += 1
        self._sync_buttons()
        await interaction.response.edit_message(
            content=event_page_content(self.rows, self.page, self.heading),
            view=self,
        )


def _safe_http_url(value: str | None) -> str | None:
    if not value:
        return None
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def _official_event_url(event: Event) -> str | None:
    url = _safe_http_url(event.source_url)
    if not url:
        return None

    parsed = urlparse(url)
    if "pokemon.com" not in parsed.netloc.casefold():
        return None

    path = parsed.path.rstrip("/").casefold()
    if path.endswith("play-pokemon-tournaments"):
        return None

    return url


def _game_label(game: str | None) -> str | None:
    if not game:
        return None

    labels = {
        "tcg": "Pokémon TCG",
        "vgc": "Pokémon VGC",
        "go": "Pokémon GO",
    }
    return labels.get(game.casefold(), game.upper())


def _clean_location_value(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = re.sub(r"\bNone\b", "", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r",\s*,+", ",", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.strip(" ,")
    return cleaned or None


def _event_location(event: Event) -> str | None:
    venue = _clean_location_value(event.venue_name)
    address = _clean_location_value(event.address)
    city = _clean_location_value(event.city)
    postcode = _clean_location_value(event.postcode)

    lines: list[str] = []

    if venue:
        lines.append(f"**{venue}**")

    if address:
        lines.append(address)

    locality = " · ".join(part for part in (city, postcode) if part)
    if locality:
        address_text = (address or "").casefold()
        if not all(
            part.casefold() in address_text
            for part in (city, postcode)
            if part
        ):
            lines.append(locality)

    return "\n".join(lines) if lines else None


def _event_embed(
    event: Event,
    league_name: str | None = None,
    *,
    preview: bool = False,
) -> discord.Embed:
    official_url = _official_event_url(event)
    game = _game_label(event.game)
    location = _event_location(event)

    sections: list[str] = []

    if preview:
        sections.extend(
            [
                "### 🧪 Test preview",
                "-# This is not a live announcement.",
                "",
            ]
        )

    event_summary = " · ".join(
        part
        for part in (game, event.event_type, league_name)
        if part
    )
    sections.extend(
        [
            "### 🎟️ Event",
            event_summary or "Play! Pokémon event",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
            "### 📅 When",
            discord.utils.format_dt(event.starts_at, style="F"),
            discord.utils.format_dt(event.starts_at, style="R"),
        ]
    )

    if location:
        sections.extend(
            [
                "",
                "━━━━━━━━━━━━━━━━━━━━",
                "",
                "### 📍 Where",
                location,
            ]
        )

    embed = discord.Embed(
        title=event.title[:256],
        url=official_url,
        description="\n".join(sections),
        timestamp=event.starts_at,
    )
    embed.set_footer(text="PokEvent 3.0 · Play! Pokémon")
    return embed

def _event_link_view(event: Event) -> discord.ui.View | None:
    official_url = _official_event_url(event)
    registration_url = _safe_http_url(event.registration_url)

    if not official_url and not registration_url:
        return None

    view = discord.ui.View(timeout=None)

    if official_url:
        view.add_item(
            discord.ui.Button(
                label="View on Pokémon",
                style=discord.ButtonStyle.link,
                url=official_url,
                emoji="🔗",
            )
        )

    if registration_url and registration_url != official_url:
        view.add_item(
            discord.ui.Button(
                label="Register",
                style=discord.ButtonStyle.link,
                url=registration_url,
                emoji="📝",
            )
        )

    return view


bot = PokEventBot()
pokevent = app_commands.Group(name="pokevent", description="PokEvent 3.0")
league_group = app_commands.Group(
    name="league",
    description="Configure this server's Play! Pokémon Leagues.",
)
eventchannel_group = app_commands.Group(
    name="eventchannel",
    description="Configure automatic PokEvent announcement channels.",
)


async def _discord_channel(channel_id: str) -> discord.TextChannel | None:
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return None
    return channel if isinstance(channel, discord.TextChannel) else None


def _thread_name(event: Event) -> str:
    prefix = "Event discussion · "
    available = max(1, 100 - len(prefix))
    return f"{prefix}{event.title[:available]}"


async def _create_event_thread(
    message: discord.Message,
    event: Event,
) -> discord.Thread | None:
    if not settings.create_event_threads:
        return None

    try:
        return await message.create_thread(
            name=_thread_name(event),
            auto_archive_duration=1440,
            reason="PokEvent event discussion thread",
        )
    except (discord.Forbidden, discord.HTTPException):
        log.exception(
            "failed to create event thread message=%s event=%s",
            message.id,
            event.id,
        )
        return None


def _event_cleanup_at(event: Event) -> datetime:
    if event.ends_at is not None and event.ends_at > event.starts_at:
        event_end = event.ends_at
    else:
        event_end = event.starts_at + timedelta(
            hours=settings.event_default_duration_hours
        )

    return event_end + timedelta(hours=settings.event_cleanup_grace_hours)


async def _delete_thread(thread_id: str | None) -> None:
    if not thread_id:
        return

    channel = bot.get_channel(int(thread_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(thread_id))
        except discord.NotFound:
            return
        except (discord.Forbidden, discord.HTTPException):
            log.exception("failed to fetch event thread=%s for cleanup", thread_id)
            return

    if not isinstance(channel, discord.Thread):
        return

    try:
        await channel.delete(reason="PokEvent event has finished")
    except discord.NotFound:
        return
    except (discord.Forbidden, discord.HTTPException):
        log.exception("failed to delete event thread=%s", thread_id)


async def _delete_published_message(
    published: PublishedMessage,
) -> None:
    await _delete_thread(published.thread_id)

    channel = await _discord_channel(published.channel_id)
    if channel is None:
        return

    try:
        message = await channel.fetch_message(int(published.message_id))
        await message.delete()
    except discord.NotFound:
        return
    except (discord.Forbidden, discord.HTTPException):
        log.exception(
            "failed to delete expired event message=%s",
            published.message_id,
        )


def _summary_event_line(event: Event) -> str:
    title = discord.utils.escape_markdown(event.title)
    if len(title) > 82:
        title = f"{title[:79]}..."

    official_url = _official_event_url(event)
    if official_url:
        title = f"[{title}]({official_url})"

    bits = [
        discord.utils.format_dt(event.starts_at, style="d"),
        title,
    ]
    game = _game_label(event.game)
    if game:
        bits.append(game)
    return " · ".join(bits)


def _summary_embed(
    leagues: list[GuildLeague],
    events: list[Event],
    default_league_id: str | None,
) -> discord.Embed:
    events_by_league: dict[str, list[Event]] = {}
    for event in events:
        if event.upstream_organisation_id is None:
            continue
        events_by_league.setdefault(event.upstream_organisation_id, []).append(event)

    ordered = sorted(
        leagues,
        key=lambda league: (
            league.league_id != default_league_id,
            league.name.casefold(),
        ),
    )

    embed = discord.Embed(
        title="📌 Upcoming Pokémon Events",
        description=(
            "A rolling view of events for the Leagues configured on this server. "
            "New events are announced separately."
        ),
    )

    for league in ordered[:25]:
        rows = events_by_league.get(league.league_id, [])
        if rows:
            visible = rows[:8]
            value = "\n".join(_summary_event_line(event) for event in visible)
            if len(rows) > len(visible):
                value += f"\n-# +{len(rows) - len(visible)} more — use /events"
        else:
            value = "-# No upcoming events currently listed."

        label = f"⭐ {league.name}" if league.league_id == default_league_id else league.name
        embed.add_field(name=label[:256], value=value[:1024], inline=False)

    if len(ordered) > 25:
        embed.description = (
            f"{embed.description}\n\n"
            f"-# {len(ordered) - 25} additional configured Leagues are not shown "
            "in this summary."
        )

    embed.set_footer(text="PokEvent 3.0 · updates automatically")
    return embed


def _embed_hash(embed: discord.Embed) -> str:
    payload = json.dumps(embed.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


async def _delete_summary_message(summary: ChannelSummary) -> None:
    channel = await _discord_channel(summary.channel_id)
    if channel is None:
        return
    try:
        message = await channel.fetch_message(int(summary.message_id))
        await message.delete()
    except discord.NotFound:
        return
    except (discord.Forbidden, discord.HTTPException):
        log.exception(
            "failed to delete stale summary message=%s",
            summary.message_id,
        )


async def refresh_guild_summary_messages(guild_id: str) -> int:
    now = datetime.now(UTC)

    async with SessionFactory() as session:
        config = await ensure_guild_config(session, guild_id)
        routes = list(
            (
                await session.scalars(
                    select(Route).where(
                        Route.guild_id == guild_id,
                        Route.enabled.is_(True),
                        Route.upstream_organisation_id.is_not(None),
                    )
                )
            ).all()
        )
        leagues = await guild_leagues(session, guild_id)
        league_by_id = {league.league_id: league for league in leagues}

        grouped_routes: dict[str, list[Route]] = {}
        for route in routes:
            if route.upstream_organisation_id not in league_by_id:
                continue
            grouped_routes.setdefault(route.channel_id, []).append(route)

        existing = list(
            (
                await session.scalars(
                    select(ChannelSummary).where(ChannelSummary.guild_id == guild_id)
                )
            ).all()
        )
        existing_by_channel = {summary.channel_id: summary for summary in existing}

        for summary in existing:
            if summary.channel_id in grouped_routes:
                continue
            await _delete_summary_message(summary)
            await session.delete(summary)

        refreshed = 0
        for channel_id, channel_routes in grouped_routes.items():
            channel = await _discord_channel(channel_id)
            if channel is None:
                continue

            channel_leagues = [
                league_by_id[route.upstream_organisation_id]
                for route in channel_routes
                if route.upstream_organisation_id in league_by_id
            ]
            league_ids = [league.league_id for league in channel_leagues]
            events = list(
                (
                    await session.scalars(
                        select(Event)
                        .where(
                            Event.status == "active",
                            Event.starts_at >= now,
                            Event.upstream_organisation_id.in_(league_ids),
                        )
                        .order_by(Event.starts_at)
                    )
                ).all()
            )

            embed = _summary_embed(
                channel_leagues,
                events,
                config.default_league_id,
            )
            content_hash = _embed_hash(embed)
            summary = existing_by_channel.get(channel_id)
            message: discord.Message | None = None

            if summary is not None:
                try:
                    message = await channel.fetch_message(int(summary.message_id))
                except discord.NotFound:
                    message = None
                except (discord.Forbidden, discord.HTTPException):
                    log.exception(
                        "failed to fetch summary message=%s",
                        summary.message_id,
                    )
                    continue

            if message is None:
                try:
                    message = await channel.send(embed=embed)
                    try:
                        await message.pin(reason="PokEvent upcoming events summary")
                    except (discord.Forbidden, discord.HTTPException):
                        log.exception(
                            "failed to pin summary in channel=%s",
                            channel_id,
                        )
                except (discord.Forbidden, discord.HTTPException):
                    log.exception(
                        "failed to create summary in channel=%s",
                        channel_id,
                    )
                    continue

                if summary is None:
                    summary = ChannelSummary(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        message_id=str(message.id),
                        content_hash=content_hash,
                    )
                    session.add(summary)
                else:
                    summary.message_id = str(message.id)
                    summary.content_hash = content_hash
                refreshed += 1
                continue

            if not message.pinned:
                try:
                    await message.pin(reason="PokEvent upcoming events summary")
                except (discord.Forbidden, discord.HTTPException):
                    log.exception(
                        "failed to pin summary in channel=%s",
                        channel_id,
                    )

            if summary is not None and summary.content_hash != content_hash:
                try:
                    await message.edit(embed=embed)
                except (discord.Forbidden, discord.HTTPException):
                    log.exception(
                        "failed to update summary message=%s",
                        summary.message_id,
                    )
                    continue
                summary.content_hash = content_hash
                refreshed += 1

        await session.commit()
        return refreshed


async def _backfill_target(guild_id: str, target: str, count: int) -> int:
    count = max(0, min(count, 10))
    if count == 0:
        return 0

    async with SessionFactory() as session:
        config = await ensure_guild_config(session, guild_id)
        key = target.strip().casefold()

        if key == "all":
            if not config.all_channel_id:
                raise ValueError("The all-Leagues announcement channel is not configured.")
            routes = list(
                (
                    await session.scalars(
                        select(Route).where(
                            Route.guild_id == guild_id,
                            Route.enabled.is_(True),
                            Route.channel_id == config.all_channel_id,
                            Route.upstream_organisation_id
                            != config.default_league_id,
                        )
                    )
                ).all()
            )
        else:
            if key == "default":
                if not config.default_league_id:
                    raise ValueError("This server does not have a default League yet.")
                league = await session.scalar(
                    select(GuildLeague).where(
                        GuildLeague.guild_id == guild_id,
                        GuildLeague.league_id == config.default_league_id,
                    )
                )
            else:
                league = await resolve_guild_league(session, guild_id, target)

            if league is None:
                raise ValueError(f"Unknown League: {target}")

            route = await session.scalar(
                select(Route).where(
                    Route.guild_id == guild_id,
                    Route.upstream_organisation_id == league.league_id,
                    Route.enabled.is_(True),
                )
            )
            routes = [route] if route is not None else []

        if not routes:
            raise ValueError("That target does not have an announcement channel configured.")

        leagues = await guild_leagues(session, guild_id)
        league_names = {league.league_id: league.name for league in leagues}

        candidates: list[tuple[Route, Event]] = []
        for route in routes:
            if route.upstream_organisation_id is None:
                continue
            events = list(
                (
                    await session.scalars(
                        select(Event)
                        .where(
                            Event.status == "active",
                            Event.starts_at >= datetime.now(UTC),
                            Event.upstream_organisation_id
                            == route.upstream_organisation_id,
                        )
                        .order_by(Event.starts_at)
                    )
                ).all()
            )
            for event in events:
                already_published = await session.scalar(
                    select(PublishedMessage.id).where(
                        PublishedMessage.route_id == route.id,
                        PublishedMessage.event_id == event.id,
                    )
                )
                if already_published is None:
                    candidates.append((route, event))

        candidates.sort(key=lambda item: item[1].starts_at)
        posted = 0

        for route, event in candidates[:count]:
            channel = await _discord_channel(route.channel_id)
            if channel is None:
                continue

            league_name = league_names.get(route.upstream_organisation_id or "")
            try:
                message = await channel.send(
                    embed=_event_embed(event, league_name),
                    view=_event_link_view(event),
                )
                thread = await _create_event_thread(message, event)
            except (discord.Forbidden, discord.HTTPException):
                log.exception(
                    "failed to backfill event=%s route=%s",
                    event.id,
                    route.id,
                )
                continue

            session.add(
                PublishedMessage(
                    route_id=route.id,
                    event_id=event.id,
                    guild_id=route.guild_id,
                    channel_id=str(channel.id),
                    message_id=str(message.id),
                    thread_id=str(thread.id) if thread is not None else None,
                    last_content_hash=event.content_hash,
                )
            )
            posted += 1

        await session.commit()
        return posted


async def _publish_route(route: Route) -> None:
    if route.baseline_at is None or route.upstream_organisation_id is None:
        return

    now = datetime.now(UTC)
    async with SessionFactory() as session:
        league = await session.scalar(
            select(GuildLeague).where(
                GuildLeague.guild_id == route.guild_id,
                GuildLeague.league_id == route.upstream_organisation_id,
            )
        )
        league_name = league.name if league is not None else None

        events = list(
            (
                await session.scalars(
                    select(Event)
                    .where(
                        Event.status == "active",
                        Event.starts_at >= now,
                        Event.upstream_organisation_id
                        == route.upstream_organisation_id,
                    )
                    .order_by(Event.starts_at)
                )
            ).all()
        )

        for event in events:
            published = await session.scalar(
                select(PublishedMessage).where(
                    PublishedMessage.route_id == route.id,
                    PublishedMessage.event_id == event.id,
                )
            )

            if published is None:
                if not route.announce_new or event.first_seen_at <= route.baseline_at:
                    continue

                channel = await _discord_channel(route.channel_id)
                if channel is None:
                    log.warning(
                        "cannot publish route=%s channel=%s",
                        route.id,
                        route.channel_id,
                    )
                    continue

                try:
                    message = await channel.send(
                        embed=_event_embed(event, league_name),
                        view=_event_link_view(event),
                    )
                    thread = await _create_event_thread(message, event)
                except (discord.Forbidden, discord.HTTPException):
                    log.exception(
                        "failed to publish event=%s route=%s",
                        event.id,
                        route.id,
                    )
                    continue

                session.add(
                    PublishedMessage(
                        route_id=route.id,
                        event_id=event.id,
                        guild_id=route.guild_id,
                        channel_id=str(channel.id),
                        message_id=str(message.id),
                        thread_id=str(thread.id) if thread is not None else None,
                        last_content_hash=event.content_hash,
                    )
                )
                continue

            if (
                not route.announce_updates
                or published.last_content_hash == event.content_hash
            ):
                continue

            channel = await _discord_channel(published.channel_id)
            if channel is None:
                continue

            try:
                message = await channel.fetch_message(int(published.message_id))
                await message.edit(
                    embed=_event_embed(event, league_name),
                    view=_event_link_view(event),
                )
            except discord.NotFound:
                try:
                    message = await channel.send(
                        embed=_event_embed(event, league_name),
                        view=_event_link_view(event),
                    )
                    thread = await _create_event_thread(message, event)
                except (discord.Forbidden, discord.HTTPException):
                    continue
                published.message_id = str(message.id)
                published.channel_id = str(channel.id)
                published.thread_id = (
                    str(thread.id) if thread is not None else None
                )
            except (discord.Forbidden, discord.HTTPException):
                log.exception(
                    "failed to update event=%s route=%s",
                    event.id,
                    route.id,
                )
                continue

            published.last_content_hash = event.content_hash

        await session.commit()


@tasks.loop(minutes=1)
async def publish_event_routes() -> None:
    async with SessionFactory() as session:
        routes = list(
            (
                await session.scalars(
                    select(Route).where(
                        Route.enabled.is_(True),
                        Route.baseline_at.is_not(None),
                    )
                )
            ).all()
        )

    for route in routes:
        await _publish_route(route)


@tasks.loop(minutes=15)
async def cleanup_expired_event_posts() -> None:
    now = datetime.now(UTC)

    async with SessionFactory() as session:
        rows = list(
            (
                await session.execute(
                    select(PublishedMessage, Event)
                    .join(Event, PublishedMessage.event_id == Event.id)
                )
            ).all()
        )

        expired: list[PublishedMessage] = []
        for published, event in rows:
            if _event_cleanup_at(event) <= now:
                expired.append(published)

        for published in expired:
            await _delete_published_message(published)
            await session.delete(published)

        if expired:
            await session.commit()
            log.info("removed %s expired Discord event posts", len(expired))


@tasks.loop(minutes=5)
async def refresh_channel_summaries() -> None:
    async with SessionFactory() as session:
        route_guild_ids = set(
            (
                await session.scalars(
                    select(Route.guild_id).where(Route.enabled.is_(True)).distinct()
                )
            ).all()
        )
        summary_guild_ids = set(
            (
                await session.scalars(
                    select(ChannelSummary.guild_id).distinct()
                )
            ).all()
        )

    for guild_id in route_guild_ids | summary_guild_ids:
        try:
            await refresh_guild_summary_messages(guild_id)
        except Exception:
            log.exception("failed to refresh event summaries for guild=%s", guild_id)


@refresh_channel_summaries.before_loop
async def before_refresh_channel_summaries() -> None:
    await bot.wait_until_ready()


@cleanup_expired_event_posts.before_loop
async def before_cleanup_expired_event_posts() -> None:
    await bot.wait_until_ready()


@publish_event_routes.before_loop
async def before_publish_event_routes() -> None:
    await bot.wait_until_ready()


async def _guild_choices(
    interaction: discord.Interaction,
    current: str,
    *,
    include_special: bool = False,
) -> list[app_commands.Choice[str]]:
    if interaction.guild_id is None:
        return []

    async with SessionFactory() as session:
        leagues = await guild_leagues(session, str(interaction.guild_id))
        await session.commit()

    needle = current.casefold().strip()
    choices: list[app_commands.Choice[str]] = []

    if include_special:
        specials = (
            ("Default", "default"),
            ("All non-default Leagues", "all"),
        )
        choices.extend(
            app_commands.Choice(name=name, value=value)
            for name, value in specials
            if not needle or needle in name.casefold() or needle in value
        )

    choices.extend(
        app_commands.Choice(name=league.name, value=league.name)
        for league in leagues
        if not needle
        or needle in league.name.casefold()
        or needle in league.league_id.casefold()
    )
    return choices[:25]


async def _league_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await _guild_choices(interaction, current)


async def _events_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await _guild_choices(interaction, current)


async def _channel_target_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await _guild_choices(interaction, current, include_special=True)


async def _send_error(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def _admin_only(command):
    command = app_commands.guild_only()(command)
    command = app_commands.default_permissions(administrator=True)(command)
    return app_commands.checks.has_permissions(administrator=True)(command)


async def _validate_announcement_channel(
    guild: discord.Guild,
    channel_id: int,
) -> tuple[discord.TextChannel | None, str | None]:
    bot_member = guild.me
    if bot_member is None:
        return None, "I could not resolve my server permissions."

    resolved = guild.get_channel(channel_id)
    if resolved is None:
        try:
            resolved = await bot.fetch_channel(channel_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return (
                None,
                "I could not access that channel. Please check my channel permissions.",
            )

    if not isinstance(resolved, discord.TextChannel):
        return None, "Please choose a normal text channel for PokEvent announcements."

    permissions = resolved.permissions_for(bot_member)
    required_permissions = {
        "View Channel": permissions.view_channel,
        "Send Messages": permissions.send_messages,
        "Create Public Threads": permissions.create_public_threads,
        "Manage Threads": permissions.manage_threads,
        "Manage Messages": permissions.manage_messages,
    }
    missing = [name for name, allowed in required_permissions.items() if not allowed]
    if missing:
        return (
            None,
            f"I need these permissions in {resolved.mention}: **{', '.join(missing)}**.",
        )

    return resolved, None


class SetupLeagueSelect(discord.ui.Select):
    def __init__(self, wizard: SetupWizard) -> None:
        self.wizard = wizard
        options = [
            discord.SelectOption(
                label=name[:100],
                value=league_id,
                description=f"League ID {league_id}"[:100],
                default=league_id == wizard.default_league_id,
            )
            for league_id, name in wizard.leagues.items()
        ][:25]
        super().__init__(
            placeholder="Choose this server's default League",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.wizard.choose_default_league(interaction, self.values[0])


class SetupChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, wizard: SetupWizard, purpose: str) -> None:
        self.wizard = wizard
        self.purpose = purpose
        placeholder = (
            "Choose the default League announcement channel"
            if purpose == "default"
            else "Choose the channel for other configured Leagues"
        )
        super().__init__(
            placeholder=placeholder,
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        await self.wizard.choose_channel(
            interaction,
            self.purpose,
            selected.id,
        )


class SetupActionButton(discord.ui.Button):
    def __init__(
        self,
        wizard: SetupWizard,
        action: str,
        label: str,
        style: discord.ButtonStyle,
    ) -> None:
        self.wizard = wizard
        self.action = action
        super().__init__(label=label, style=style)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.wizard.handle_action(interaction, self.action)


class SetupBackfillButton(discord.ui.Button):
    def __init__(self, wizard: SetupWizard, count: int) -> None:
        self.wizard = wizard
        self.count = count
        label = "No full cards" if count == 0 else f"Post next {count}"
        style = (
            discord.ButtonStyle.secondary
            if count == 0
            else discord.ButtonStyle.primary
        )
        super().__init__(label=label, style=style)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.wizard.finish(interaction, self.count)


class SetupWizard(discord.ui.View):
    def __init__(
        self,
        *,
        invoker_id: int,
        guild_id: str,
        leagues: list[GuildLeague],
        default_league_id: str | None,
        default_channel_id: str | None,
        all_channel_id: str | None,
    ) -> None:
        super().__init__(timeout=600)
        self.invoker_id = invoker_id
        self.guild_id = guild_id
        self.leagues = {league.league_id: league.name for league in leagues}
        self.default_league_id = default_league_id
        self.default_channel_id = default_channel_id
        self.all_channel_id = all_channel_id
        self.show_league_step()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(
            "Only the administrator who started this setup can use these controls.",
            ephemeral=True,
        )
        return False

    def _reset(self) -> None:
        self.clear_items()

    def show_league_step(self) -> None:
        self._reset()
        self.add_item(SetupLeagueSelect(self))

    def show_default_channel_step(self) -> None:
        self._reset()
        self.add_item(SetupChannelSelect(self, "default"))

    def show_other_channel_step(self) -> None:
        self._reset()
        self.add_item(
            SetupActionButton(
                self,
                "same",
                "Use the same channel",
                discord.ButtonStyle.primary,
            )
        )
        self.add_item(
            SetupActionButton(
                self,
                "different",
                "Choose another channel",
                discord.ButtonStyle.secondary,
            )
        )
        self.add_item(
            SetupActionButton(
                self,
                "none",
                "Don't auto-post other Leagues",
                discord.ButtonStyle.secondary,
            )
        )

    def show_other_channel_picker(self) -> None:
        self._reset()
        self.add_item(SetupChannelSelect(self, "all"))

    def show_backfill_step(self) -> None:
        self._reset()
        for count in (0, 3, 5, 10):
            self.add_item(SetupBackfillButton(self, count))

    def _league_name(self) -> str:
        if self.default_league_id is None:
            return "Not set"
        return self.leagues.get(self.default_league_id, self.default_league_id)

    async def choose_default_league(
        self,
        interaction: discord.Interaction,
        league_id: str,
    ) -> None:
        async with SessionFactory() as session:
            chosen = await set_default_league(session, self.guild_id, league_id)
            await session.commit()

        self.default_league_id = chosen.league_id
        self.show_default_channel_step()
        await interaction.response.edit_message(
            content=(
                "## PokEvent setup · 2/4\n"
                f"Default League: **{chosen.name}**\n\n"
                "Choose the channel where this League's event cards and pinned "
                "upcoming-events summary should appear."
            ),
            view=self,
        )

    async def choose_channel(
        self,
        interaction: discord.Interaction,
        purpose: str,
        channel_id: int,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This setup must be run inside a server.",
                ephemeral=True,
            )
            return

        channel, error = await _validate_announcement_channel(
            interaction.guild,
            channel_id,
        )
        if channel is None:
            await interaction.response.send_message(
                error or "Invalid channel.",
                ephemeral=True,
            )
            return

        async with SessionFactory() as session:
            await set_event_channel(
                session,
                self.guild_id,
                purpose,
                str(channel.id),
            )
            await session.commit()

        if purpose == "default":
            self.default_channel_id = str(channel.id)
            self.show_other_channel_step()
            await interaction.response.edit_message(
                content=(
                    "## PokEvent setup · 3/4\n"
                    f"Default League: **{self._league_name()}**\n"
                    f"Default channel: {channel.mention}\n\n"
                    "What should PokEvent do with your **other configured Leagues**? "
                    "You can still give individual Leagues their own channel later."
                ),
                view=self,
            )
            return

        self.all_channel_id = str(channel.id)
        self.show_backfill_step()
        await interaction.response.edit_message(
            content=(
                "## PokEvent setup · 4/4\n"
                f"Other configured Leagues will use {channel.mention}.\n\n"
                "The pinned summary will make all existing upcoming events visible. "
                "How many already-known **default League** events should also be "
                "posted now as full cards with discussion threads?"
            ),
            view=self,
        )

    async def handle_action(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "different":
            self.show_other_channel_picker()
            await interaction.response.edit_message(
                content=(
                    "## PokEvent setup · 3/4\n"
                    "Choose the channel for all non-default configured Leagues. "
                    "Specific League channel overrides can be added later."
                ),
                view=self,
            )
            return

        async with SessionFactory() as session:
            if action == "same":
                if self.default_channel_id is None:
                    await interaction.response.send_message(
                        "Choose the default channel first.",
                        ephemeral=True,
                    )
                    return
                await set_event_channel(
                    session,
                    self.guild_id,
                    "all",
                    self.default_channel_id,
                )
                self.all_channel_id = self.default_channel_id
            elif action == "none":
                await clear_event_channel(session, self.guild_id, "all")
                self.all_channel_id = None
            else:
                await interaction.response.send_message(
                    "Unknown setup action.",
                    ephemeral=True,
                )
                return
            await session.commit()

        self.show_backfill_step()
        await interaction.response.edit_message(
            content=(
                "## PokEvent setup · 4/4\n"
                "The pinned summary will make existing upcoming events visible "
                "without flooding the channel.\n\n"
                "How many already-known **default League** events should also be "
                "posted now as full cards with discussion threads?"
            ),
            view=self,
        )

    async def finish(
        self,
        interaction: discord.Interaction,
        backfill_count: int,
    ) -> None:
        await interaction.response.defer()
        await refresh_guild_summary_messages(self.guild_id)

        posted = 0
        if backfill_count:
            try:
                posted = await _backfill_target(
                    self.guild_id,
                    "default",
                    backfill_count,
                )
            except ValueError:
                log.exception("setup backfill failed for guild=%s", self.guild_id)

        default_channel = (
            f"<#{self.default_channel_id}>"
            if self.default_channel_id
            else "Not configured"
        )
        other_channel = (
            f"<#{self.all_channel_id}>"
            if self.all_channel_id
            else "No automatic posts"
        )

        await interaction.edit_original_response(
            content=(
                "## ✅ PokEvent setup complete\n"
                f"**Default League:** {self._league_name()}\n"
                f"**Default channel:** {default_channel}\n"
                f"**Other configured Leagues:** {other_channel}\n"
                f"**Existing full cards posted:** {posted}\n\n"
                "The pinned summary now shows existing upcoming events. "
                "New events will be announced automatically.\n\n"
                "Add another League any time with /league add."
            ),
            view=None,
        )
        self.stop()


@pokevent.command(name="status", description="Show the PokEvent service status.")
async def status(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        f"PokEvent {__version__} is online.",
        ephemeral=True,
    )


@pokevent.command(
    name="setup",
    description="Run the guided PokEvent setup for this server.",
)
@_admin_only
async def pokevent_setup(interaction: discord.Interaction) -> None:
    assert interaction.guild_id is not None

    guild_id = str(interaction.guild_id)
    async with SessionFactory() as session:
        config = await ensure_guild_config(session, guild_id)
        leagues = await guild_leagues(session, guild_id)
        await session.commit()

    if not leagues:
        await interaction.response.send_message(
            "There are no Leagues configured yet. Add one with /league add, "
            "then run /pokevent setup again.",
            ephemeral=True,
        )
        return

    wizard = SetupWizard(
        invoker_id=interaction.user.id,
        guild_id=guild_id,
        leagues=leagues,
        default_league_id=config.default_league_id,
        default_channel_id=config.default_channel_id,
        all_channel_id=config.all_channel_id,
    )

    league_lines = "\n".join(
        f"• **{league.name}** · League ID {league.league_id}"
        for league in leagues[:10]
    )
    if len(leagues) > 10:
        league_lines += f"\n• …and {len(leagues) - 10} more"

    await interaction.response.send_message(
        "## PokEvent setup · 1/4\n"
        "Choose this server's **default League**. This is what /events shows "
        "when no League is specified.\n\n"
        f"{league_lines}\n\n"
        "-# Additional Leagues can be added later with /league add.",
        view=wizard,
        ephemeral=True,
    )


@bot.tree.command(name="events", description="Browse upcoming Pokémon events.")
@app_commands.guild_only()
@app_commands.describe(
    league="Leave blank for the server default, or choose a configured League.",
)
async def events(
    interaction: discord.Interaction,
    league: str | None = None,
) -> None:
    assert interaction.guild_id is not None
    guild_id = str(interaction.guild_id)
    selector = (league or "default").strip()

    async with SessionFactory() as session:
        config = await ensure_guild_config(session, guild_id)

        if selector.casefold() == "default":
            if not config.default_league_id:
                await session.commit()
                await interaction.response.send_message(
                    "This server does not have a default League yet. "
                    "A server administrator can run /pokevent setup or "
                    "set one with /league default.",
                    ephemeral=True,
                )
                return
            chosen = await session.scalar(
                select(GuildLeague).where(
                    GuildLeague.guild_id == guild_id,
                    GuildLeague.league_id == config.default_league_id,
                )
            )
        else:
            chosen = await resolve_guild_league(session, guild_id, selector)

        if chosen is None:
            await session.commit()
            await interaction.response.send_message(
                f"I don't know a League called **{selector}** on this server.",
                ephemeral=True,
            )
            return

        heading = f"{chosen.name} events"
        statement = (
            select(Event)
            .where(
                Event.starts_at >= datetime.now(UTC),
                Event.status == "active",
                Event.upstream_organisation_id == chosen.league_id,
            )
            .order_by(Event.starts_at)
            .limit(EVENTS_QUERY_LIMIT)
        )

        rows = list((await session.scalars(statement)).all())
        await session.commit()

    if not rows:
        await interaction.response.send_message(
            f"No upcoming events are currently available for "
            f"**{heading.removesuffix(' events')}**.",
            ephemeral=True,
        )
        return

    view = EventPagerView(rows, heading)
    await interaction.response.send_message(
        event_page_content(rows, 0, heading),
        view=view,
        ephemeral=True,
    )


@events.autocomplete("league")
async def events_league_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await _events_autocomplete(interaction, current)


@league_group.command(name="add", description="Add a Play! Pokémon League to this server.")
@_admin_only
@app_commands.describe(name="Friendly League name", league_id="Play! Pokémon League ID")
async def league_add(
    interaction: discord.Interaction,
    name: str,
    league_id: str,
) -> None:
    assert interaction.guild_id is not None
    try:
        async with SessionFactory() as session:
            added = await add_guild_league(
                session,
                str(interaction.guild_id),
                name,
                league_id,
            )
            await session.commit()
    except ValueError as exc:
        await _send_error(interaction, str(exc))
        return

    await refresh_guild_summary_messages(str(interaction.guild_id))
    await interaction.response.send_message(
        f"Added **{added.name}** ({added.league_id}). "
        "Its events will be picked up on the next catalogue sync.",
        ephemeral=True,
    )


@league_group.command(name="remove", description="Remove a League from this server.")
@_admin_only
@app_commands.describe(league="League to remove")
async def league_remove(interaction: discord.Interaction, league: str) -> None:
    assert interaction.guild_id is not None
    try:
        async with SessionFactory() as session:
            removed = await remove_guild_league(
                session,
                str(interaction.guild_id),
                league,
            )
            await session.commit()
    except ValueError as exc:
        await _send_error(interaction, str(exc))
        return

    await refresh_guild_summary_messages(str(interaction.guild_id))
    await interaction.response.send_message(
        f"Removed **{removed.name}** ({removed.league_id}).",
        ephemeral=True,
    )


@league_remove.autocomplete("league")
async def league_remove_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await _league_autocomplete(interaction, current)


@league_group.command(name="rename", description="Rename a configured League.")
@_admin_only
@app_commands.describe(league="League to rename", name="New friendly name")
async def league_rename(
    interaction: discord.Interaction,
    league: str,
    name: str,
) -> None:
    assert interaction.guild_id is not None
    try:
        async with SessionFactory() as session:
            renamed = await rename_guild_league(
                session,
                str(interaction.guild_id),
                league,
                name,
            )
            await session.commit()
    except ValueError as exc:
        await _send_error(interaction, str(exc))
        return

    await refresh_guild_summary_messages(str(interaction.guild_id))
    await interaction.response.send_message(
        f"League renamed to **{renamed.name}** ({renamed.league_id}).",
        ephemeral=True,
    )


@league_rename.autocomplete("league")
async def league_rename_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await _league_autocomplete(interaction, current)


@league_group.command(name="default", description="Set this server's default League.")
@_admin_only
@app_commands.describe(league="League to use when /events has no parameter")
async def league_default(interaction: discord.Interaction, league: str) -> None:
    assert interaction.guild_id is not None
    try:
        async with SessionFactory() as session:
            chosen = await set_default_league(
                session,
                str(interaction.guild_id),
                league,
            )
            await session.commit()
    except ValueError as exc:
        await _send_error(interaction, str(exc))
        return

    await refresh_guild_summary_messages(str(interaction.guild_id))
    await interaction.response.send_message(
        f"**{chosen.name}** ({chosen.league_id}) is now this server's default League.",
        ephemeral=True,
    )


@league_default.autocomplete("league")
async def league_default_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await _league_autocomplete(interaction, current)


@league_group.command(name="list", description="List the Leagues configured on this server.")
@app_commands.guild_only()
async def league_list(interaction: discord.Interaction) -> None:
    assert interaction.guild_id is not None
    async with SessionFactory() as session:
        config = await ensure_guild_config(session, str(interaction.guild_id))
        leagues = await guild_leagues(session, str(interaction.guild_id))
        await session.commit()

    if not leagues:
        await interaction.response.send_message(
            "No Leagues are configured on this server.",
            ephemeral=True,
        )
        return

    lines = []
    for configured in leagues:
        marker = (
            " **(default)**"
            if configured.league_id == config.default_league_id
            else ""
        )
        origin = "server" if configured.origin == "server" else "service"
        lines.append(
            f"• **{configured.name}** — {configured.league_id}{marker} · {origin}"
        )
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@eventchannel_group.command(
    name="set",
    description="Set an automatic event announcement channel.",
)
@_admin_only
@app_commands.describe(
    target="default, all, or a configured League",
    channel="Channel where matching new events should be posted",
)
async def eventchannel_set(
    interaction: discord.Interaction,
    target: str,
    channel: app_commands.AppCommandChannel,
) -> None:
    assert interaction.guild_id is not None
    assert interaction.guild is not None

    bot_member = interaction.guild.me
    if bot_member is None:
        await _send_error(interaction, "I could not resolve my server permissions.")
        return

    resolved_channel = interaction.guild.get_channel(channel.id)
    if resolved_channel is None:
        try:
            resolved_channel = await bot.fetch_channel(channel.id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            await _send_error(
                interaction,
                "I could not access that channel. Please check my channel permissions.",
            )
            return

    if not isinstance(resolved_channel, discord.TextChannel):
        await _send_error(
            interaction,
            "Please choose a normal text channel for PokEvent announcements.",
        )
        return

    permissions = resolved_channel.permissions_for(bot_member)
    required_permissions = {
        "View Channel": permissions.view_channel,
        "Send Messages": permissions.send_messages,
        "Create Public Threads": permissions.create_public_threads,
        "Manage Threads": permissions.manage_threads,
        "Manage Messages": permissions.manage_messages,
    }
    missing_permissions = [
        name for name, allowed in required_permissions.items() if not allowed
    ]
    if missing_permissions:
        await _send_error(
            interaction,
            f"I need these permissions in {resolved_channel.mention}: "
            f"**{', '.join(missing_permissions)}**.",
        )
        return

    try:
        async with SessionFactory() as session:
            description = await set_event_channel(
                session,
                str(interaction.guild_id),
                target,
                str(resolved_channel.id),
            )
            await session.commit()
        await refresh_guild_summary_messages(str(interaction.guild_id))
    except ValueError as exc:
        await _send_error(interaction, str(exc))
        return

    await interaction.response.send_message(
        f"Automatic posts for **{description}** will go to "
        f"{resolved_channel.mention}.",
        ephemeral=True,
    )


@eventchannel_set.autocomplete("target")
async def eventchannel_set_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await _channel_target_autocomplete(interaction, current)


@eventchannel_group.command(
    name="test",
    description="Send a preview of an automatic event announcement.",
)
@_admin_only
@app_commands.describe(target="default, all, or a configured League")
async def eventchannel_test(
    interaction: discord.Interaction,
    target: str,
) -> None:
    assert interaction.guild_id is not None
    guild_id = str(interaction.guild_id)

    try:
        async with SessionFactory() as session:
            league, channel_id = await resolve_event_channel(
                session,
                guild_id,
                target,
            )

            if channel_id is None:
                await session.commit()
                await _send_error(
                    interaction,
                    "That target does not have an announcement channel configured.",
                )
                return

            if league is None:
                config = await ensure_guild_config(session, guild_id)
                statement = (
                    select(Event)
                    .where(
                        Event.starts_at >= datetime.now(UTC),
                        Event.status == "active",
                        Event.upstream_organisation_id
                        != config.default_league_id,
                    )
                    .order_by(Event.starts_at)
                    .limit(1)
                )
                league_name = "Configured League"
            else:
                statement = (
                    select(Event)
                    .where(
                        Event.starts_at >= datetime.now(UTC),
                        Event.status == "active",
                        Event.upstream_organisation_id == league.league_id,
                    )
                    .order_by(Event.starts_at)
                    .limit(1)
                )
                league_name = league.name

            event = await session.scalar(statement)
            await session.commit()

        if event is None:
            await _send_error(
                interaction,
                "I could not find an upcoming event to use as a preview.",
            )
            return

        channel = await _discord_channel(channel_id)
        if channel is None:
            await _send_error(
                interaction,
                "I could not access the configured announcement channel.",
            )
            return

        await channel.send(
            embed=_event_embed(event, league_name, preview=True),
            view=_event_link_view(event),
        )
        await interaction.response.send_message(
            f"Sent a test event card to {channel.mention}.",
            ephemeral=True,
        )
    except ValueError as exc:
        await _send_error(interaction, str(exc))


@eventchannel_test.autocomplete("target")
async def eventchannel_test_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await _channel_target_autocomplete(interaction, current)


@eventchannel_group.command(
    name="backfill",
    description="Post a small number of already-known upcoming events.",
)
@_admin_only
@app_commands.describe(
    target="default, all, or a configured League",
    count="Number of existing events to publish now (maximum 10)",
)
async def eventchannel_backfill(
    interaction: discord.Interaction,
    target: str,
    count: app_commands.Range[int, 1, 10] = 3,
) -> None:
    assert interaction.guild_id is not None

    try:
        posted = await _backfill_target(
            str(interaction.guild_id),
            target,
            int(count),
        )
        await refresh_guild_summary_messages(str(interaction.guild_id))
    except ValueError as exc:
        await _send_error(interaction, str(exc))
        return

    await interaction.response.send_message(
        f"Published **{posted}** existing event card"
        f"{'s' if posted != 1 else ''}.",
        ephemeral=True,
    )


@eventchannel_backfill.autocomplete("target")
async def eventchannel_backfill_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await _channel_target_autocomplete(interaction, current)


@eventchannel_group.command(
    name="clear",
    description="Clear an automatic event announcement channel.",
)
@_admin_only
@app_commands.describe(target="default, all, or a configured League")
async def eventchannel_clear(interaction: discord.Interaction, target: str) -> None:
    assert interaction.guild_id is not None
    try:
        async with SessionFactory() as session:
            description = await clear_event_channel(
                session,
                str(interaction.guild_id),
                target,
            )
            await session.commit()
        await refresh_guild_summary_messages(str(interaction.guild_id))
    except ValueError as exc:
        await _send_error(interaction, str(exc))
        return

    await interaction.response.send_message(
        f"Cleared the automatic post channel for **{description}**.",
        ephemeral=True,
    )


@eventchannel_clear.autocomplete("target")
async def eventchannel_clear_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return await _channel_target_autocomplete(interaction, current)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        await _send_error(
            interaction,
            "You need the Administrator permission to change PokEvent configuration.",
        )
        return
    raise error


bot.tree.add_command(pokevent)
bot.tree.add_command(league_group)
bot.tree.add_command(eventchannel_group)


async def run_bot() -> None:
    if not settings.discord_token:
        raise RuntimeError("POKEVENT_DISCORD_TOKEN is required to run the Discord bot.")
    await bot.start(settings.discord_token)


def main() -> None:
    asyncio.run(run_bot())

from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime

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
    resolve_guild_league,
    set_default_league,
    set_event_channel,
)
from .models import Event, GuildLeague, PublishedMessage, Route

settings = get_settings()
log = logging.getLogger("pokevent.discord")

EVENTS_PAGE_SIZE = 10
EVENTS_QUERY_LIMIT = 250


class PokEventBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

    async def setup_hook(self) -> None:
        await self.tree.sync()
        if not publish_event_routes.is_running():
            publish_event_routes.start()


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


def _event_embed(event: Event) -> discord.Embed:
    embed = discord.Embed(
        title=event.title[:256],
        url=event.source_url or None,
        timestamp=event.starts_at,
    )
    if event.game:
        embed.add_field(name="Game", value=event.game.upper(), inline=True)
    if event.event_type:
        embed.add_field(name="Event", value=event.event_type, inline=True)
    location = ", ".join(part for part in (event.venue_name, event.city) if part)
    if location:
        embed.add_field(name="Venue", value=location[:1024], inline=False)
    embed.set_footer(text="PokEvent 3.0")
    return embed


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


async def _publish_route(route: Route) -> None:
    if route.baseline_at is None or route.upstream_organisation_id is None:
        return

    now = datetime.now(UTC)
    async with SessionFactory() as session:
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
                    message = await channel.send(embed=_event_embed(event))
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
                await message.edit(embed=_event_embed(event))
            except discord.NotFound:
                try:
                    message = await channel.send(embed=_event_embed(event))
                except (discord.Forbidden, discord.HTTPException):
                    continue
                published.message_id = str(message.id)
                published.channel_id = str(channel.id)
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
            ("Nearby", "nearby"),
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
    return await _guild_choices(interaction, current, include_special=True)


async def _channel_target_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    choices = await _guild_choices(interaction, current, include_special=True)
    return [choice for choice in choices if choice.value != "nearby"]


async def _send_error(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def _admin_only(command):
    command = app_commands.guild_only()(command)
    command = app_commands.default_permissions(administrator=True)(command)
    return app_commands.checks.has_permissions(administrator=True)(command)


@pokevent.command(name="status", description="Show the PokEvent service status.")
async def status(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        f"PokEvent {__version__} is online.",
        ephemeral=True,
    )


@bot.tree.command(name="events", description="Browse upcoming Pokémon events.")
@app_commands.guild_only()
@app_commands.describe(
    league="Leave blank for the server default, choose a League, or choose nearby.",
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

        if selector.casefold() == "nearby":
            heading = "Nearby Pokémon events"
            statement = (
                select(Event)
                .where(Event.starts_at >= datetime.now(UTC), Event.status == "active")
                .order_by(Event.starts_at)
                .limit(EVENTS_QUERY_LIMIT)
            )
        else:
            if selector.casefold() == "default":
                if not config.default_league_id:
                    await session.commit()
                    await interaction.response.send_message(
                        "This server does not have a default League yet. "
                        "A server administrator can set one with /league default.",
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
    channel: discord.TextChannel,
) -> None:
    assert interaction.guild_id is not None
    assert interaction.guild is not None

    bot_member = interaction.guild.me
    if bot_member is None:
        await _send_error(interaction, "I could not resolve my server permissions.")
        return

    permissions = channel.permissions_for(bot_member)
    if not permissions.view_channel or not permissions.send_messages:
        await _send_error(
            interaction,
            f"I need View Channel and Send Messages permission in {channel.mention}.",
        )
        return

    try:
        async with SessionFactory() as session:
            description = await set_event_channel(
                session,
                str(interaction.guild_id),
                target,
                str(channel.id),
            )
            await session.commit()
    except ValueError as exc:
        await _send_error(interaction, str(exc))
        return

    await interaction.response.send_message(
        f"Automatic posts for **{description}** will go to {channel.mention}.",
        ephemeral=True,
    )


@eventchannel_set.autocomplete("target")
async def eventchannel_set_autocomplete(
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

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import math
import random
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from sqlalchemy import or_, select

from . import __version__
from .config import get_settings
from .db import SessionFactory
from .event_policy import (
    CARD_EVENT_TYPES,
    DEFAULT_CARD_EVENT_TYPES,
    effective_card_event_types,
    event_card_type,
)
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
        intents.members = settings.enable_member_welcomes
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

    async def on_member_join(self, member: discord.Member) -> None:
        if not settings.enable_member_welcomes or member.bot:
            return
        try:
            await _send_member_welcome(member)
        except Exception:
            log.exception(
                "failed to send member welcome guild=%s member=%s",
                member.guild.id,
                member.id,
            )


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

    if event.status == "cancelled":
        sections.extend(
            [
                "### ❌ Event cancelled",
                "This event is marked as cancelled by the source.",
                "",
                "━━━━━━━━━━━━━━━━━━━━",
                "",
            ]
        )

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

    title = event.title
    if event.status == "cancelled":
        title = f"❌ CANCELLED · {title}"

    embed = discord.Embed(
        title=title[:256],
        url=official_url,
        description="\n".join(sections),
        timestamp=event.starts_at,
        colour=discord.Colour.red() if event.status == "cancelled" else None,
    )
    embed.set_footer(text="PokÈvent 3.0 · Play! Pokémon")
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

    if (
        event.status != "cancelled"
        and registration_url
        and registration_url != official_url
    ):
        view.add_item(
            discord.ui.Button(
                label="Register",
                style=discord.ButtonStyle.link,
                url=registration_url,
                emoji="📝",
            )
        )

    return view


POKEMON_WELCOME_MESSAGES = (
    "A wild {member} appeared! Welcome to **{server}**! ✨",
    "Professor Oak says hello, {member}! Welcome to **{server}**! 🌿",
    "{member} joined the party! Your Pokémon adventure in **{server}** starts now! 🎒",
    "Welcome, {member}! May your catches be shiny and your top-decks be perfect. ✨",
    "{member} has entered the tall grass! Welcome to **{server}**! 🌱",
    "A new Trainer approaches! Welcome to **{server}**, {member}! ⚡",
    "{member}, I choose you! Welcome to **{server}**! 🔴",
    "The Pokédex has been updated: {member} is now part of **{server}**! 📱",
    "Welcome to **{server}**, {member}! Your next great Pokémon adventure starts here. 🗺️",
    "{member} used Join Server — it's super effective! Welcome to **{server}**! 💥",
    "Another Trainer has arrived! Give {member} a warm welcome to **{server}**! 👋",
    "Welcome, {member}! Grab your deck, charge your Poké Balls, and make yourself at home in **{server}**! 🎴",
)


def _event_announcement_mentions(
    config,
    channel: discord.TextChannel,
) -> tuple[str | None, discord.AllowedMentions]:
    mode = (config.event_mention_mode or "none").casefold()
    bot_member = channel.guild.me
    permissions = (
        channel.permissions_for(bot_member)
        if bot_member is not None
        else None
    )

    if mode == "everyone":
        if permissions is not None and permissions.mention_everyone:
            return (
                "@everyone",
                discord.AllowedMentions(
                    everyone=True,
                    roles=False,
                    users=False,
                    replied_user=False,
                ),
            )
        return None, discord.AllowedMentions.none()

    if mode == "roles":
        roles: list[discord.Role] = []
        for role_id in config.event_mention_role_ids or []:
            try:
                role = channel.guild.get_role(int(role_id))
            except (TypeError, ValueError):
                role = None
            if role is None or role.is_default():
                continue
            if role.mentionable or (
                permissions is not None and permissions.mention_everyone
            ):
                roles.append(role)

        if roles:
            return (
                " ".join(role.mention for role in roles),
                discord.AllowedMentions(
                    everyone=False,
                    roles=roles,
                    users=False,
                    replied_user=False,
                ),
            )

    return None, discord.AllowedMentions.none()


def _welcome_message(member: discord.Member, template: str | None) -> str:
    message = (
        template.strip()
        if template and template.strip()
        else random.choice(POKEMON_WELCOME_MESSAGES)
    )
    return (
        message.replace("{member}", member.mention)
        .replace("{display_name}", member.display_name)
        .replace("{server}", member.guild.name)
    )[:2000]


def _banner_text(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: max(1, limit - 1)]}…"


def _render_welcome_banner(
    *,
    member_name: str,
    server_name: str,
    avatar_bytes: bytes | None = None,
    guild_icon_bytes: bytes | None = None,
) -> io.BytesIO:
    width, height = 1200, 400

    if guild_icon_bytes:
        try:
            with Image.open(io.BytesIO(guild_icon_bytes)) as source:
                background = ImageOps.fit(
                    source.convert("RGB"),
                    (width, height),
                    method=Image.Resampling.LANCZOS,
                ).filter(ImageFilter.GaussianBlur(radius=22))
        except (OSError, ValueError):
            background = Image.new("RGB", (width, height), (37, 42, 54))
    else:
        background = Image.new("RGB", (width, height), (37, 42, 54))

    canvas = background.convert("RGBA")
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 130))
    canvas = Image.alpha_composite(canvas, overlay)

    avatar_size = 230
    avatar_x = 70
    avatar_y = (height - avatar_size) // 2
    if avatar_bytes:
        try:
            with Image.open(io.BytesIO(avatar_bytes)) as source:
                avatar = ImageOps.fit(
                    source.convert("RGBA"),
                    (avatar_size, avatar_size),
                    method=Image.Resampling.LANCZOS,
                )
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            ImageDraw.Draw(mask).ellipse(
                (0, 0, avatar_size - 1, avatar_size - 1),
                fill=255,
            )
            ring = Image.new("RGBA", (avatar_size + 12, avatar_size + 12), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse(
                (0, 0, avatar_size + 11, avatar_size + 11),
                fill=(255, 255, 255, 225),
            )
            canvas.alpha_composite(ring, (avatar_x - 6, avatar_y - 6))
            canvas.paste(avatar, (avatar_x, avatar_y), mask)
        except (OSError, ValueError):
            avatar_bytes = None

    if not avatar_bytes:
        placeholder = Image.new("RGBA", (avatar_size, avatar_size), (255, 255, 255, 35))
        placeholder_mask = Image.new("L", (avatar_size, avatar_size), 0)
        ImageDraw.Draw(placeholder_mask).ellipse(
            (0, 0, avatar_size - 1, avatar_size - 1),
            fill=255,
        )
        canvas.paste(placeholder, (avatar_x, avatar_y), placeholder_mask)

    draw = ImageDraw.Draw(canvas)
    title_font = ImageFont.load_default(size=34)
    member_font = ImageFont.load_default(size=62)
    server_font = ImageFont.load_default(size=30)

    text_x = 350
    draw.text(
        (text_x, 105),
        "WELCOME TO",
        font=title_font,
        fill=(255, 255, 255, 210),
    )
    draw.text(
        (text_x, 155),
        _banner_text(member_name, 30),
        font=member_font,
        fill=(255, 255, 255, 255),
    )
    draw.text(
        (text_x, 245),
        _banner_text(server_name, 42),
        font=server_font,
        fill=(255, 255, 255, 225),
    )

    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


async def _welcome_banner_file(member: discord.Member) -> discord.File:
    avatar_bytes: bytes | None = None
    guild_icon_bytes: bytes | None = None

    try:
        avatar_bytes = await member.display_avatar.read()
    except (discord.HTTPException, OSError):
        pass

    if member.guild.icon is not None:
        try:
            guild_icon_bytes = await member.guild.icon.read()
        except (discord.HTTPException, OSError):
            pass

    buffer = _render_welcome_banner(
        member_name=member.display_name,
        server_name=member.guild.name,
        avatar_bytes=avatar_bytes,
        guild_icon_bytes=guild_icon_bytes,
    )
    return discord.File(buffer, filename="pokevent-welcome.png")


async def _send_member_welcome(
    member: discord.Member,
    *,
    preview: bool = False,
) -> bool:
    async with SessionFactory() as session:
        config = await ensure_guild_config(session, str(member.guild.id))
        mode = (config.welcome_mode or "off").casefold()
        channel_id = config.welcome_channel_id
        template = config.welcome_message
        await session.commit()

    if mode not in {"text", "image"} or not channel_id:
        return False

    channel = await _discord_channel(channel_id)
    if channel is None or channel.guild.id != member.guild.id:
        return False

    bot_member = channel.guild.me
    if bot_member is None:
        return False
    permissions = channel.permissions_for(bot_member)
    if not permissions.view_channel or not permissions.send_messages:
        return False
    if mode == "image" and not permissions.attach_files:
        return False

    content = _welcome_message(member, template)
    if preview:
        content = f"-# 🧪 Test welcome preview\n{content}"

    allowed_mentions = discord.AllowedMentions(
        everyone=False,
        roles=False,
        users=[member],
        replied_user=False,
    )

    try:
        if mode == "image":
            await channel.send(
                content=content,
                file=await _welcome_banner_file(member),
                allowed_mentions=allowed_mentions,
            )
        else:
            await channel.send(
                content=content,
                allowed_mentions=allowed_mentions,
            )
        return True
    except (discord.Forbidden, discord.HTTPException):
        log.exception(
            "failed to send welcome guild=%s member=%s",
            member.guild.id,
            member.id,
        )
        return False


def _event_snapshot(event: Event) -> dict:
    return {
        "title": event.title,
        "game": event.game,
        "event_type": event.event_type,
        "status": event.status,
        "starts_at": int(event.starts_at.timestamp()),
        "ends_at": int(event.ends_at.timestamp()) if event.ends_at else None,
        "venue_name": _clean_location_value(event.venue_name),
        "address": _clean_location_value(event.address),
        "city": _clean_location_value(event.city),
        "postcode": _clean_location_value(event.postcode),
        "registration_url": _safe_http_url(event.registration_url),
        "source_url": _safe_http_url(event.source_url),
    }


def _snapshot_datetime(value: object) -> str:
    if isinstance(value, int):
        return f"<t:{value}:F>"
    return "Not specified"


def _snapshot_text(value: object) -> str:
    if value is None or value == "":
        return "Not specified"
    return str(value)


def _event_update_notice(
    previous: dict | None,
    event: Event,
) -> str:
    current = _event_snapshot(event)

    if previous is None:
        if event.status == "cancelled":
            return (
                "### ❌ Event cancelled\n"
                "This event has been marked as cancelled. "
                "The announcement card has been updated."
            )
        return (
            "### 🔄 Event details updated\n"
            "The organiser has changed this event's details. "
            "The announcement card has been updated."
        )

    lines: list[str] = []

    old_status = previous.get("status")
    status_changed = old_status != current["status"]
    if status_changed:
        if current["status"] == "cancelled":
            lines.append("### ❌ Event cancelled")
        elif old_status == "cancelled":
            lines.append("### ✅ Event active again")
        else:
            lines.append("### 🔄 Event status updated")
    else:
        lines.append("### 🔄 Event details updated")

    changes: list[str] = []
    if status_changed:
        changes.append(
            f"**Status:** {_snapshot_text(old_status).title()} "
            f"→ {_snapshot_text(current['status']).title()}"
        )

    if previous.get("title") != current["title"]:
        changes.append(
            f"**Name:** {_snapshot_text(previous.get('title'))} "
            f"→ {_snapshot_text(current['title'])}"
        )

    if previous.get("starts_at") != current["starts_at"]:
        changes.append(
            f"**Date/time:** {_snapshot_datetime(previous.get('starts_at'))} "
            f"→ {_snapshot_datetime(current['starts_at'])}"
        )

    if previous.get("venue_name") != current["venue_name"]:
        changes.append(
            f"**Venue:** {_snapshot_text(previous.get('venue_name'))} "
            f"→ {_snapshot_text(current['venue_name'])}"
        )

    old_address = " · ".join(
        str(value)
        for value in (
            previous.get("address"),
            previous.get("city"),
            previous.get("postcode"),
        )
        if value
    )
    new_address = " · ".join(
        str(value)
        for value in (
            current["address"],
            current["city"],
            current["postcode"],
        )
        if value
    )
    if old_address != new_address:
        changes.append(
            f"**Location:** {_snapshot_text(old_address)} "
            f"→ {_snapshot_text(new_address)}"
        )

    if previous.get("event_type") != current["event_type"]:
        changes.append(
            f"**Event type:** {_snapshot_text(previous.get('event_type'))} "
            f"→ {_snapshot_text(current['event_type'])}"
        )

    if previous.get("game") != current["game"]:
        changes.append(
            f"**Game:** {_snapshot_text(previous.get('game'))} "
            f"→ {_snapshot_text(current['game'])}"
        )

    if previous.get("registration_url") != current["registration_url"]:
        changes.append("**Registration link:** updated")

    if previous.get("source_url") != current["source_url"]:
        changes.append("**Official event link:** updated")

    if not changes:
        changes.append("The source changed event details not shown on the card.")

    lines.extend(changes[:8])
    lines.append("")
    lines.append("-# The announcement card above has been updated automatically.")

    notice = "\n".join(lines)
    return notice[:2000]


async def _event_thread(thread_id: str | None) -> discord.Thread | None:
    if not thread_id:
        return None

    channel = bot.get_channel(int(thread_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(thread_id))
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return None

    return channel if isinstance(channel, discord.Thread) else None


async def _notify_event_thread(
    thread_id: str | None,
    event: Event,
    content: str,
) -> bool:
    thread = await _event_thread(thread_id)
    if thread is None:
        return False

    try:
        if thread.archived and not thread.locked:
            await thread.edit(
                archived=False,
                reason="PokÈvent event details changed",
            )
        if thread.name != _thread_name(event):
            await thread.edit(
                name=_thread_name(event),
                reason="PokÈvent event title changed",
            )
        await thread.send(
            content,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True
    except (discord.Forbidden, discord.HTTPException):
        log.exception("failed to notify event thread=%s", thread_id)
        return False


bot = PokEventBot()
pokevent = app_commands.Group(name="pokevent", description="PokÈvent 3.0")
league_group = app_commands.Group(
    name="league",
    description="Configure this server's Play! Pokémon Leagues.",
)
eventchannel_group = app_commands.Group(
    name="eventchannel",
    description="Configure automatic PokÈvent announcement channels.",
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
            reason="PokÈvent event discussion thread",
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


async def _delete_thread(thread_id: str | None) -> bool:
    if not thread_id:
        return True

    channel = bot.get_channel(int(thread_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(thread_id))
        except discord.NotFound:
            return True
        except (discord.Forbidden, discord.HTTPException):
            log.exception("failed to fetch event thread=%s for cleanup", thread_id)
            return False

    if not isinstance(channel, discord.Thread):
        return True

    try:
        await channel.delete(reason="PokÈvent event has finished")
        return True
    except discord.NotFound:
        return True
    except (discord.Forbidden, discord.HTTPException):
        log.exception("failed to delete event thread=%s", thread_id)
        return False


async def _delete_published_message(
    published: PublishedMessage,
) -> bool:
    thread_deleted = await _delete_thread(published.thread_id)

    channel = await _discord_channel(published.channel_id)
    if channel is None:
        return False

    try:
        message = await channel.fetch_message(int(published.message_id))
        await message.delete()
        message_deleted = True
    except discord.NotFound:
        message_deleted = True
    except (discord.Forbidden, discord.HTTPException):
        log.exception(
            "failed to delete expired event message=%s",
            published.message_id,
        )
        message_deleted = False

    return thread_deleted and message_deleted


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

    embed.set_footer(text="PokÈvent 3.0 · updates automatically")
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
                        await message.pin(reason="PokÈvent upcoming events summary")
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
                    await message.pin(reason="PokÈvent upcoming events summary")
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
        enabled_card_types = effective_card_event_types(config.card_event_types)
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
                if event_card_type(event.event_type) not in enabled_card_types:
                    continue

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
                    last_event_snapshot=_event_snapshot(event),
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
        config = await ensure_guild_config(session, route.guild_id)
        enabled_card_types = effective_card_event_types(config.card_event_types)
        league = await session.scalar(
            select(GuildLeague).where(
                GuildLeague.guild_id == route.guild_id,
                GuildLeague.league_id == route.upstream_organisation_id,
            )
        )
        league_name = league.name if league is not None else None

        published_event_ids = select(PublishedMessage.event_id).where(
            PublishedMessage.route_id == route.id
        )
        events = list(
            (
                await session.scalars(
                    select(Event)
                    .where(
                        Event.upstream_organisation_id
                        == route.upstream_organisation_id,
                        or_(
                            Event.starts_at >= now,
                            Event.id.in_(published_event_ids),
                        ),
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
                if event.starts_at < now or event.status != "active":
                    continue
                if event_card_type(event.event_type) not in enabled_card_types:
                    continue
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

                mention_content, allowed_mentions = _event_announcement_mentions(
                    config,
                    channel,
                )
                try:
                    message = await channel.send(
                        content=mention_content,
                        embed=_event_embed(event, league_name),
                        view=_event_link_view(event),
                        allowed_mentions=allowed_mentions,
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
                        last_event_snapshot=_event_snapshot(event),
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

            previous_snapshot = published.last_event_snapshot
            notice = _event_update_notice(previous_snapshot, event)

            try:
                message = await channel.fetch_message(int(published.message_id))
                await message.edit(
                    embed=_event_embed(event, league_name),
                    view=_event_link_view(event),
                )

                if published.thread_id is None and settings.create_event_threads:
                    thread = await _create_event_thread(message, event)
                    published.thread_id = (
                        str(thread.id) if thread is not None else None
                    )

                await _notify_event_thread(
                    published.thread_id,
                    event,
                    notice,
                )
            except discord.NotFound:
                if not await _delete_thread(published.thread_id):
                    continue
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
                await _notify_event_thread(
                    published.thread_id,
                    event,
                    notice,
                )
            except (discord.Forbidden, discord.HTTPException):
                log.exception(
                    "failed to update event=%s route=%s",
                    event.id,
                    route.id,
                )
                continue

            published.last_content_hash = event.content_hash
            published.last_event_snapshot = _event_snapshot(event)

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

        removed = 0
        for published in expired:
            if await _delete_published_message(published):
                await session.delete(published)
                removed += 1

        if removed:
            await session.commit()
            log.info("removed %s expired Discord event posts", removed)


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
        return None, "Please choose a normal text channel for PokÈvent announcements."

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


async def _setup_dashboard_content(
    guild_id: str,
    *,
    notice: str | None = None,
) -> str:
    async with SessionFactory() as session:
        config = await ensure_guild_config(session, guild_id)
        leagues = await guild_leagues(session, guild_id)
        await session.commit()

    default_name = "Not set"
    for league in leagues:
        if league.league_id == config.default_league_id:
            default_name = league.name
            break

    default_channel = (
        f"<#{config.default_channel_id}>"
        if config.default_channel_id
        else "Not configured"
    )
    other_channel = (
        f"<#{config.all_channel_id}>"
        if config.all_channel_id
        else "No automatic posts"
    )
    ready = bool(config.default_league_id and config.default_channel_id)
    status = "✅ Ready" if ready else "⚠️ Setup incomplete"
    enabled_card_types = effective_card_event_types(config.card_event_types)
    mention_mode = (config.event_mention_mode or "none").casefold()
    mention_label = {
        "none": "None",
        "everyone": "@everyone",
        "roles": "Selected roles",
    }.get(mention_mode, "None")
    welcome_mode = (config.welcome_mode or "off").casefold()
    welcome_label = {
        "off": "Off",
        "text": "Text",
        "image": "Image banner",
    }.get(welcome_mode, "Off")
    league_names = ", ".join(league.name for league in leagues[:6]) or "None"
    if len(leagues) > 6:
        league_names += f" +{len(leagues) - 6} more"

    lines = [
        "## ⚙️ PokÈvent Admin",
        f"**Status:** {status}",
        f"**Default League:** {default_name}",
        f"**Default channel:** {default_channel}",
        f"**Other configured Leagues:** {other_channel}",
        f"**Configured Leagues:** {len(leagues)} · {league_names}",
        f"**Announcement card types:** {len(enabled_card_types)}/{len(CARD_EVENT_TYPES)} enabled",
        f"**New-event notifications:** {mention_label}",
        f"**Member welcomes:** {welcome_label}",
        "",
    ]
    if notice:
        lines.extend(["", f"**{notice}**"])
    return "\n".join(lines)


async def _preview_event_target(
    guild_id: str,
    target: str,
) -> tuple[discord.TextChannel, Event, str | None]:
    async with SessionFactory() as session:
        league, channel_id = await resolve_event_channel(
            session,
            guild_id,
            target,
        )
        if channel_id is None:
            raise ValueError("That target does not have an announcement channel configured.")

        if league is None:
            config = await ensure_guild_config(session, guild_id)
            routes = list(
                (
                    await session.scalars(
                        select(Route).where(
                            Route.guild_id == guild_id,
                            Route.enabled.is_(True),
                            Route.channel_id == channel_id,
                            Route.upstream_organisation_id
                            != config.default_league_id,
                        )
                    )
                ).all()
            )
            league_ids = [
                route.upstream_organisation_id
                for route in routes
                if route.upstream_organisation_id is not None
            ]
            statement = (
                select(Event)
                .where(
                    Event.starts_at >= datetime.now(UTC),
                    Event.status == "active",
                    Event.upstream_organisation_id.in_(league_ids),
                )
                .order_by(Event.starts_at)
                .limit(1)
            )
            league_name = None
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
        if event is None:
            raise ValueError("I could not find an upcoming event to use as a preview.")

        if league_name is None:
            configured = await session.scalar(
                select(GuildLeague).where(
                    GuildLeague.guild_id == guild_id,
                    GuildLeague.league_id == event.upstream_organisation_id,
                )
            )
            league_name = configured.name if configured is not None else None

        await session.commit()

    channel = await _discord_channel(channel_id)
    if channel is None:
        raise ValueError("I could not access the configured announcement channel.")

    return channel, event, league_name


class SetupDashboardButton(discord.ui.Button):
    def __init__(
        self,
        dashboard: SetupDashboardView,
        action: str,
        label: str,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        *,
        row: int | None = None,
    ) -> None:
        self.dashboard = dashboard
        self.action = action
        super().__init__(label=label, style=style, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.dashboard.handle_action(interaction, self.action)


class SetupDashboardView(discord.ui.View):
    def __init__(self, *, invoker_id: int, guild_id: str) -> None:
        super().__init__(timeout=600)
        self.invoker_id = invoker_id
        self.guild_id = guild_id
        self.add_item(
            SetupDashboardButton(
                self,
                "guided",
                "Guided Setup",
                discord.ButtonStyle.primary,
                row=0,
            )
        )
        self.add_item(SetupDashboardButton(self, "add", "Add League", row=0))
        self.add_item(SetupDashboardButton(self, "manage", "Manage Leagues", row=0))
        self.add_item(SetupDashboardButton(self, "channels", "Channels", row=0))
        self.add_item(SetupDashboardButton(self, "notifications", "Notifications", row=0))
        self.add_item(SetupDashboardButton(self, "types", "Event Types", row=1))
        self.add_item(SetupDashboardButton(self, "posts", "Event Posts", row=1))
        self.add_item(SetupDashboardButton(self, "welcomes", "Welcomes", row=1))
        self.add_item(SetupDashboardButton(self, "refresh", "Refresh Summary", row=1))
        self.add_item(SetupDashboardButton(self, "close", "Close", row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(
            "Only the administrator who opened this setup can use these controls.",
            ephemeral=True,
        )
        return False

    async def handle_action(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "add":
            await interaction.response.send_modal(
                AddLeagueModal(
                    invoker_id=self.invoker_id,
                    guild_id=self.guild_id,
                )
            )
            return

        if action == "manage":
            async with SessionFactory() as session:
                config = await ensure_guild_config(session, self.guild_id)
                leagues = await guild_leagues(session, self.guild_id)
                await session.commit()
            if not leagues:
                await interaction.response.send_message(
                    "No Leagues are configured yet. Use **Add League** first.",
                    ephemeral=True,
                )
                return
            view = LeagueManagerView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
                leagues=leagues,
                default_league_id=config.default_league_id,
            )
            await interaction.response.edit_message(
                content=view.content(),
                view=view,
            )
            return

        if action == "channels":
            async with SessionFactory() as session:
                config = await ensure_guild_config(session, self.guild_id)
                leagues = await guild_leagues(session, self.guild_id)
                await session.commit()
            if not leagues:
                await interaction.response.send_message(
                    "Add at least one League before configuring channels.",
                    ephemeral=True,
                )
                return
            view = ChannelManagerView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
                leagues=leagues,
                default_league_id=config.default_league_id,
            )
            await interaction.response.edit_message(
                content=await view.content(),
                view=view,
            )
            return

        if action == "notifications":
            async with SessionFactory() as session:
                config = await ensure_guild_config(session, self.guild_id)
                await session.commit()
            view = EventNotificationManagerView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
                mode=(config.event_mention_mode or "none"),
                role_ids=set(config.event_mention_role_ids or []),
            )
            await interaction.response.edit_message(
                content=view.content(),
                view=view,
            )
            return

        if action == "welcomes":
            async with SessionFactory() as session:
                config = await ensure_guild_config(session, self.guild_id)
                await session.commit()
            view = WelcomeManagerView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
                mode=(config.welcome_mode or "off"),
                channel_id=config.welcome_channel_id,
                message=config.welcome_message,
            )
            await interaction.response.edit_message(
                content=view.content(),
                view=view,
            )
            return

        if action == "types":
            async with SessionFactory() as session:
                config = await ensure_guild_config(session, self.guild_id)
                enabled = effective_card_event_types(config.card_event_types)
                await session.commit()
            view = EventTypeManagerView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
                enabled=enabled,
            )
            await interaction.response.edit_message(
                content=view.content(),
                view=view,
            )
            return

        if action == "posts":
            async with SessionFactory() as session:
                leagues = await guild_leagues(session, self.guild_id)
                await session.commit()
            view = PostToolsView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
                leagues=leagues,
            )
            await interaction.response.edit_message(
                content=view.content(),
                view=view,
            )
            return

        if action == "refresh":
            await interaction.response.defer()
            refreshed = await refresh_guild_summary_messages(self.guild_id)
            await interaction.edit_original_response(
                content=await _setup_dashboard_content(
                    self.guild_id,
                    notice=f"Summary refresh complete · {refreshed} message(s) changed.",
                ),
                view=self,
            )
            return

        if action == "guided":
            async with SessionFactory() as session:
                config = await ensure_guild_config(session, self.guild_id)
                leagues = await guild_leagues(session, self.guild_id)
                await session.commit()
            if not leagues:
                await interaction.response.send_modal(
                    AddLeagueModal(
                        invoker_id=self.invoker_id,
                        guild_id=self.guild_id,
                    )
                )
                return
            wizard = SetupWizard(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
                leagues=leagues,
                default_league_id=config.default_league_id,
                default_channel_id=config.default_channel_id,
                all_channel_id=config.all_channel_id,
            )
            league_lines = "\n".join(
                f"• **{league.name}** · League ID {league.league_id}"
                for league in leagues[:10]
            )
            await interaction.response.edit_message(
                content=(
                    "## PokÈvent setup · 1/4\n"
                    "Choose this server's **default League**. This is what /events "
                    "shows when no League is specified.\n\n"
                    f"{league_lines}"
                ),
                view=wizard,
            )
            return

        if action == "close":
            await interaction.response.edit_message(
                content="PokÈvent setup closed. Run /pokevent setup to reopen it.",
                view=None,
            )
            self.stop()
            return


class EventMentionModeSelect(discord.ui.Select):
    def __init__(self, manager: EventNotificationManagerView) -> None:
        self.manager = manager
        options = [
            discord.SelectOption(
                label="No notification",
                value="none",
                description="Post cards without pinging anyone",
                default=manager.mode == "none",
            ),
            discord.SelectOption(
                label="@everyone",
                value="everyone",
                description="Ping everyone for new automatic event cards",
                default=manager.mode == "everyone",
            ),
            discord.SelectOption(
                label="Selected roles",
                value="roles",
                description="Ping one or more chosen Discord roles",
                default=manager.mode == "roles",
            ),
        ]
        super().__init__(
            placeholder="Choose notification behaviour",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.manager.mode = self.values[0]
        await self.manager.save()
        self.manager.rebuild()
        await interaction.response.edit_message(
            content=self.manager.content(notice="Notification setting updated."),
            view=self.manager,
        )


class EventMentionRoleSelect(discord.ui.RoleSelect):
    def __init__(self, manager: EventNotificationManagerView) -> None:
        self.manager = manager
        super().__init__(
            placeholder="Choose roles to ping for new event cards",
            min_values=1,
            max_values=10,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.manager.role_ids = {
            str(role.id)
            for role in self.values
            if not role.is_default()
        }
        self.manager.mode = "roles"
        await self.manager.save()
        self.manager.rebuild()
        await interaction.response.edit_message(
            content=self.manager.content(notice="Notification roles updated."),
            view=self.manager,
        )


class EventNotificationBackButton(discord.ui.Button):
    def __init__(self, manager: EventNotificationManagerView) -> None:
        self.manager = manager
        super().__init__(label="Back", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = SetupDashboardView(
            invoker_id=self.manager.invoker_id,
            guild_id=self.manager.guild_id,
        )
        await interaction.response.edit_message(
            content=await _setup_dashboard_content(self.manager.guild_id),
            view=view,
        )


class EventNotificationManagerView(discord.ui.View):
    def __init__(
        self,
        *,
        invoker_id: int,
        guild_id: str,
        mode: str,
        role_ids: set[str],
    ) -> None:
        super().__init__(timeout=600)
        self.invoker_id = invoker_id
        self.guild_id = guild_id
        self.mode = mode if mode in {"none", "everyone", "roles"} else "none"
        self.role_ids = set(role_ids)
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(
            "Only the administrator who opened this setup can use these controls.",
            ephemeral=True,
        )
        return False

    async def save(self) -> None:
        async with SessionFactory() as session:
            config = await ensure_guild_config(session, self.guild_id)
            config.event_mention_mode = self.mode
            config.event_mention_role_ids = sorted(self.role_ids)
            await session.commit()

    def content(self, notice: str | None = None) -> str:
        mode_label = {
            "none": "No notification",
            "everyone": "@everyone",
            "roles": "Selected roles",
        }[self.mode]
        lines = [
            "## 🔔 New Event Notifications",
            f"**Mode:** {mode_label}",
        ]
        if self.mode == "roles":
            selected = (
                " ".join(f"<@&{role_id}>" for role_id in sorted(self.role_ids))
                if self.role_ids
                else "No roles selected yet"
            )
            lines.append(f"**Roles:** {selected}")
        lines.extend(
            [
                "",
                "Notifications are added only to genuinely new automatic event cards.",
                "-# Test posts, backfills, card updates and lifecycle notices never ping.",
                (
                    "-# @everyone and non-mentionable roles require the bot to have "
                    "the relevant Discord mention permission in the announcement channel."
                ),
            ]
        )
        if notice:
            lines.extend(["", f"**{notice}**"])
        return "\n".join(lines)

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(EventMentionModeSelect(self))
        if self.mode == "roles":
            self.add_item(EventMentionRoleSelect(self))
        self.add_item(EventNotificationBackButton(self))


async def _validate_welcome_channel(
    guild: discord.Guild,
    channel_id: int,
    *,
    image_mode: bool,
) -> tuple[discord.TextChannel | None, str | None]:
    resolved = guild.get_channel(channel_id)
    if resolved is None:
        try:
            resolved = await bot.fetch_channel(channel_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return None, "I could not access that welcome channel."

    if not isinstance(resolved, discord.TextChannel):
        return None, "Please choose a normal text channel for welcomes."

    bot_member = guild.me
    if bot_member is None:
        return None, "I could not resolve my server permissions."

    permissions = resolved.permissions_for(bot_member)
    missing: list[str] = []
    if not permissions.view_channel:
        missing.append("View Channel")
    if not permissions.send_messages:
        missing.append("Send Messages")
    if image_mode and not permissions.attach_files:
        missing.append("Attach Files")

    if missing:
        return (
            None,
            f"I need these permissions in {resolved.mention}: **{', '.join(missing)}**.",
        )
    return resolved, None


class WelcomeModeSelect(discord.ui.Select):
    def __init__(self, manager: WelcomeManagerView) -> None:
        self.manager = manager
        options = [
            discord.SelectOption(
                label="Off",
                value="off",
                description="Do not welcome new members",
                default=manager.mode == "off",
            ),
            discord.SelectOption(
                label="Text welcome",
                value="text",
                description="Send the configured welcome message",
                default=manager.mode == "text",
            ),
            discord.SelectOption(
                label="Image banner",
                value="image",
                description="Send a generated avatar/server welcome banner",
                default=manager.mode == "image",
            ),
        ]
        super().__init__(
            placeholder="Choose welcome style",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.manager.mode = self.values[0]
        await self.manager.save()
        self.manager.rebuild()
        notice = "Welcome setting updated."
        await interaction.response.edit_message(
            content=self.manager.content(notice=notice),
            view=self.manager,
        )


class WelcomeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, manager: WelcomeManagerView) -> None:
        self.manager = manager
        super().__init__(
            placeholder="Choose the welcome channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return

        channel, error = await _validate_welcome_channel(
            interaction.guild,
            self.values[0].id,
            image_mode=self.manager.mode == "image",
        )
        if channel is None:
            await interaction.response.send_message(
                error or "Invalid welcome channel.",
                ephemeral=True,
            )
            return

        self.manager.channel_id = str(channel.id)
        await self.manager.save()
        self.manager.rebuild()
        await interaction.response.edit_message(
            content=self.manager.content(
                notice=f"Welcome channel set to {channel.mention}."
            ),
            view=self.manager,
        )


class WelcomeButton(discord.ui.Button):
    def __init__(
        self,
        manager: WelcomeManagerView,
        action: str,
        label: str,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ) -> None:
        self.manager = manager
        self.action = action
        super().__init__(label=label, style=style, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.manager.handle_action(interaction, self.action)


class WelcomeMessageModal(discord.ui.Modal, title="Customise welcome message"):
    message_input = discord.ui.TextInput(
        label="Welcome message",
        style=discord.TextStyle.paragraph,
        placeholder="Welcome {member} to {server}! 👋",
        required=False,
        max_length=1000,
    )

    def __init__(self, manager: WelcomeManagerView) -> None:
        super().__init__()
        self.manager = manager
        if manager.message:
            self.message_input.default = manager.message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.manager.message = self.message_input.value.strip() or None
        await self.manager.save()
        self.manager.rebuild()
        await interaction.response.edit_message(
            content=self.manager.content(notice="Welcome message updated."),
            view=self.manager,
        )


class WelcomeManagerView(discord.ui.View):
    def __init__(
        self,
        *,
        invoker_id: int,
        guild_id: str,
        mode: str,
        channel_id: str | None,
        message: str | None,
    ) -> None:
        super().__init__(timeout=600)
        self.invoker_id = invoker_id
        self.guild_id = guild_id
        self.mode = mode if mode in {"off", "text", "image"} else "off"
        self.channel_id = channel_id
        self.message = message
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(
            "Only the administrator who opened this setup can use these controls.",
            ephemeral=True,
        )
        return False

    async def save(self) -> None:
        async with SessionFactory() as session:
            config = await ensure_guild_config(session, self.guild_id)
            config.welcome_mode = self.mode
            config.welcome_channel_id = self.channel_id
            config.welcome_message = self.message
            await session.commit()

    def content(self, notice: str | None = None) -> str:
        mode_label = {
            "off": "Off",
            "text": "Text",
            "image": "Image banner",
        }[self.mode]
        channel = f"<#{self.channel_id}>" if self.channel_id else "Not configured"
        message_source = "Custom message" if self.message else "Random Pokémon messages"
        lines = [
            "## 👋 Member Welcomes",
            f"**Mode:** {mode_label}",
            f"**Channel:** {channel}",
            f"**Message style:** {message_source}",
            "",
            "Available message tokens: {member}, {display_name}, {server}.",
        ]
        if self.mode == "image":
            lines.append(
                "-# Image banners use the member avatar and server icon when available."
            )
        if notice:
            lines.extend(["", f"**{notice}**"])
        return "\n".join(lines)

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(WelcomeModeSelect(self))
        if self.mode != "off":
            self.add_item(WelcomeChannelSelect(self))
            self.add_item(WelcomeButton(self, "message", "Set Custom Message"))
            if self.message:
                self.add_item(WelcomeButton(self, "random", "Use Random Messages"))
            self.add_item(
                WelcomeButton(
                    self,
                    "test",
                    "Test Welcome",
                    discord.ButtonStyle.primary,
                )
            )
        self.add_item(WelcomeButton(self, "back", "Back"))

    async def handle_action(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "message":
            await interaction.response.send_modal(WelcomeMessageModal(self))
            return

        if action == "random":
            self.message = None
            await self.save()
            self.rebuild()
            await interaction.response.edit_message(
                content=self.content(notice="Random Pokémon welcomes enabled."),
                view=self,
            )
            return

        if action == "test":
            if interaction.guild is None or not isinstance(
                interaction.user,
                discord.Member,
            ):
                await interaction.response.send_message(
                    "Welcome previews must be run inside a server.",
                    ephemeral=True,
                )
                return

            await interaction.response.defer()
            sent = await _send_member_welcome(interaction.user, preview=True)
            notice = (
                "Test welcome sent."
                if sent
                else (
                    "I could not send the test welcome. "
                    "Check the mode, channel and permissions."
                )
            )
            await interaction.edit_original_response(
                content=self.content(notice=notice),
                view=self,
            )
            return

        if action == "back":
            view = SetupDashboardView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
            )
            await interaction.response.edit_message(
                content=await _setup_dashboard_content(self.guild_id),
                view=view,
            )


class EventTypeSelect(discord.ui.Select):
    def __init__(self, manager: EventTypeManagerView) -> None:
        self.manager = manager
        descriptions = {
            "League Session": "Routine recurring League play",
            "Friendly Tournament": "Named non-premier tournament",
            "League Challenge": "Premier local League Challenge",
            "League Cup": "Premier local League Cup",
            "Pre-Release": "Set prerelease event",
            "Playtime": "Casual organised play",
            "Other / Unknown": "New or unrecognised event type",
        }
        options = [
            discord.SelectOption(
                label=event_type,
                value=event_type,
                description=descriptions[event_type],
                default=event_type in manager.enabled,
            )
            for event_type in CARD_EVENT_TYPES
        ]
        super().__init__(
            placeholder="Choose event types that create announcement cards",
            min_values=1,
            max_values=len(options),
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.manager.enabled = set(self.values)
        await self.manager.save()
        self.manager.rebuild()
        await interaction.response.edit_message(
            content=self.manager.content(notice="Announcement card types updated."),
            view=self.manager,
        )


class EventTypeButton(discord.ui.Button):
    def __init__(
        self,
        manager: EventTypeManagerView,
        action: str,
        label: str,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ) -> None:
        self.manager = manager
        self.action = action
        super().__init__(label=label, style=style, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.manager.handle_action(interaction, self.action)


class EventTypeManagerView(discord.ui.View):
    def __init__(
        self,
        *,
        invoker_id: int,
        guild_id: str,
        enabled: set[str],
    ) -> None:
        super().__init__(timeout=600)
        self.invoker_id = invoker_id
        self.guild_id = guild_id
        self.enabled = set(enabled)
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(
            "Only the administrator who opened this setup can use these controls.",
            ephemeral=True,
        )
        return False

    async def save(self) -> None:
        async with SessionFactory() as session:
            config = await ensure_guild_config(session, self.guild_id)
            config.card_event_types = [
                event_type
                for event_type in CARD_EVENT_TYPES
                if event_type in self.enabled
            ]
            await session.commit()

    def content(self, notice: str | None = None) -> str:
        lines = [
            "## 🎟️ Announcement Card Types",
            (
                "Choose which event categories create full announcement cards "
                "and discussion threads."
            ),
            "",
        ]
        lines.extend(
            f"{'✅' if event_type in self.enabled else '▫️'} **{event_type}**"
            for event_type in CARD_EVENT_TYPES
        )
        lines.extend(
            [
                "",
                (
                    "-# The pinned Upcoming Events summary and /events still show all "
                    "configured events, including League Sessions."
                ),
                (
                    "-# Changing this affects future auto-posts and backfill; it does "
                    "not delete cards that were already posted."
                ),
            ]
        )
        if notice:
            lines.extend(["", f"**{notice}**"])
        return "\n".join(lines)

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(EventTypeSelect(self))
        self.add_item(
            EventTypeButton(
                self,
                "defaults",
                "Use Defaults",
                discord.ButtonStyle.primary,
            )
        )
        self.add_item(
            EventTypeButton(
                self,
                "none",
                "Disable All Cards",
                discord.ButtonStyle.danger,
            )
        )
        self.add_item(EventTypeButton(self, "back", "Back"))

    async def handle_action(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "back":
            view = SetupDashboardView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
            )
            await interaction.response.edit_message(
                content=await _setup_dashboard_content(self.guild_id),
                view=view,
            )
            return

        if action == "defaults":
            self.enabled = set(DEFAULT_CARD_EVENT_TYPES)
            await self.save()
            self.rebuild()
            await interaction.response.edit_message(
                content=self.content(
                    notice="Default tournament-focused policy restored."
                ),
                view=self,
            )
            return

        if action == "none":
            self.enabled = set()
            await self.save()
            self.rebuild()
            await interaction.response.edit_message(
                content=self.content(notice="Automatic announcement cards disabled."),
                view=self,
            )


class AddLeagueModal(discord.ui.Modal, title="Add Play! Pokémon League"):
    name_input = discord.ui.TextInput(
        label="League name",
        placeholder="e.g. Example Pokémon League",
        max_length=100,
    )
    league_id_input = discord.ui.TextInput(
        label="League ID",
        placeholder="e.g. 1234567",
        max_length=64,
    )

    def __init__(self, *, invoker_id: int, guild_id: str) -> None:
        super().__init__()
        self.invoker_id = invoker_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            async with SessionFactory() as session:
                added = await add_guild_league(
                    session,
                    self.guild_id,
                    self.name_input.value,
                    self.league_id_input.value,
                )
                await session.commit()
            await refresh_guild_summary_messages(self.guild_id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        view = SetupDashboardView(
            invoker_id=self.invoker_id,
            guild_id=self.guild_id,
        )
        await interaction.response.edit_message(
            content=await _setup_dashboard_content(
                self.guild_id,
                notice=f"Added {added.name} ({added.league_id}).",
            ),
            view=view,
        )


class LeagueManagerSelect(discord.ui.Select):
    def __init__(self, manager: LeagueManagerView) -> None:
        self.manager = manager
        options = [
            discord.SelectOption(
                label=league.name[:100],
                value=league.league_id,
                description=f"League ID {league.league_id}"[:100],
                default=league.league_id == manager.selected_league_id,
            )
            for league in manager.leagues
        ][:25]
        super().__init__(
            placeholder="Choose a League to manage",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.manager.selected_league_id = self.values[0]
        self.manager.rebuild()
        await interaction.response.edit_message(
            content=self.manager.content(),
            view=self.manager,
        )


class LeagueManagerButton(discord.ui.Button):
    def __init__(
        self,
        manager: LeagueManagerView,
        action: str,
        label: str,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ) -> None:
        self.manager = manager
        self.action = action
        super().__init__(label=label, style=style, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.manager.handle_action(interaction, self.action)


class LeagueManagerView(discord.ui.View):
    def __init__(
        self,
        *,
        invoker_id: int,
        guild_id: str,
        leagues: list[GuildLeague],
        default_league_id: str | None,
    ) -> None:
        super().__init__(timeout=600)
        self.invoker_id = invoker_id
        self.guild_id = guild_id
        self.leagues = leagues
        self.default_league_id = default_league_id
        self.selected_league_id = (
            default_league_id
            if default_league_id in {league.league_id for league in leagues}
            else leagues[0].league_id
        )
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(
            "Only the administrator who opened this setup can use these controls.",
            ephemeral=True,
        )
        return False

    def selected(self) -> GuildLeague:
        return next(
            league
            for league in self.leagues
            if league.league_id == self.selected_league_id
        )

    def content(self) -> str:
        league = self.selected()
        marker = " · **Default**" if league.league_id == self.default_league_id else ""
        origin = "PokEvent default" if league.origin == "service" else "Server-added"
        return (
            "## 🏠 Manage Leagues\n"
            f"**{league.name}** · ID {league.league_id}{marker}\n"
            f"-# {origin}\n\n"
            "Set it as the default, rename it, remove it, or go back."
        )

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(LeagueManagerSelect(self))
        self.add_item(
            LeagueManagerButton(
                self,
                "default",
                "Set Default",
                discord.ButtonStyle.primary,
            )
        )
        self.add_item(LeagueManagerButton(self, "rename", "Rename"))
        self.add_item(
            LeagueManagerButton(
                self,
                "remove",
                "Remove",
                discord.ButtonStyle.danger,
            )
        )
        self.add_item(LeagueManagerButton(self, "back", "Back"))

    async def handle_action(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        league = self.selected()

        if action == "rename":
            await interaction.response.send_modal(
                RenameLeagueModal(
                    invoker_id=self.invoker_id,
                    guild_id=self.guild_id,
                    league_id=league.league_id,
                    current_name=league.name,
                )
            )
            return

        if action == "remove":
            view = RemoveLeagueConfirmView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
                league_id=league.league_id,
                league_name=league.name,
            )
            await interaction.response.edit_message(
                content=(
                    "## ⚠️ Remove League\n"
                    f"Remove **{league.name}** ({league.league_id}) from this server?\n\n"
                    "Its automatic route will also be removed. Existing Discord "
                    "event posts are not bulk-deleted by this action."
                ),
                view=view,
            )
            return

        if action == "default":
            async with SessionFactory() as session:
                chosen = await set_default_league(
                    session,
                    self.guild_id,
                    league.league_id,
                )
                await session.commit()
            self.default_league_id = chosen.league_id
            await refresh_guild_summary_messages(self.guild_id)
            self.rebuild()
            await interaction.response.edit_message(
                content=self.content(),
                view=self,
            )
            return

        if action == "back":
            view = SetupDashboardView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
            )
            await interaction.response.edit_message(
                content=await _setup_dashboard_content(self.guild_id),
                view=view,
            )


class RenameLeagueModal(discord.ui.Modal, title="Rename League"):
    new_name_input = discord.ui.TextInput(
        label="New League name",
        max_length=100,
    )

    def __init__(
        self,
        *,
        invoker_id: int,
        guild_id: str,
        league_id: str,
        current_name: str,
    ) -> None:
        super().__init__()
        self.invoker_id = invoker_id
        self.guild_id = guild_id
        self.league_id = league_id
        self.new_name_input.default = current_name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            async with SessionFactory() as session:
                renamed = await rename_guild_league(
                    session,
                    self.guild_id,
                    self.league_id,
                    self.new_name_input.value,
                )
                await session.commit()
            await refresh_guild_summary_messages(self.guild_id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        view = SetupDashboardView(
            invoker_id=self.invoker_id,
            guild_id=self.guild_id,
        )
        await interaction.response.edit_message(
            content=await _setup_dashboard_content(
                self.guild_id,
                notice=f"Renamed League to {renamed.name}.",
            ),
            view=view,
        )


class RemoveLeagueConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        invoker_id: int,
        guild_id: str,
        league_id: str,
        league_name: str,
    ) -> None:
        super().__init__(timeout=300)
        self.invoker_id = invoker_id
        self.guild_id = guild_id
        self.league_id = league_id
        self.league_name = league_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(
            "Only the administrator who opened this setup can use these controls.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Remove League", style=discord.ButtonStyle.danger)
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        try:
            async with SessionFactory() as session:
                await remove_guild_league(
                    session,
                    self.guild_id,
                    self.league_id,
                )
                await session.commit()
            await refresh_guild_summary_messages(self.guild_id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        view = SetupDashboardView(
            invoker_id=self.invoker_id,
            guild_id=self.guild_id,
        )
        await interaction.response.edit_message(
            content=await _setup_dashboard_content(
                self.guild_id,
                notice=f"Removed {self.league_name}.",
            ),
            view=view,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        view = SetupDashboardView(
            invoker_id=self.invoker_id,
            guild_id=self.guild_id,
        )
        await interaction.response.edit_message(
            content=await _setup_dashboard_content(self.guild_id),
            view=view,
        )
        self.stop()


class ChannelTargetSelect(discord.ui.Select):
    def __init__(self, manager: ChannelManagerView) -> None:
        self.manager = manager
        options = [
            discord.SelectOption(
                label="Default League",
                value="default",
                default=manager.selected_target == "default",
            ),
            discord.SelectOption(
                label="All non-default Leagues",
                value="all",
                default=manager.selected_target == "all",
            ),
        ]
        options.extend(
            discord.SelectOption(
                label=league.name[:100],
                value=league.league_id,
                description="Specific League override",
                default=manager.selected_target == league.league_id,
            )
            for league in manager.leagues
            if league.league_id != manager.default_league_id
        )
        super().__init__(
            placeholder="Choose what channel to configure",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.manager.selected_target = self.values[0]
        self.manager.rebuild()
        await interaction.response.edit_message(
            content=await self.manager.content(),
            view=self.manager,
        )


class ChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, manager: ChannelManagerView) -> None:
        self.manager = manager
        super().__init__(
            placeholder="Choose a new announcement channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return

        channel, error = await _validate_announcement_channel(
            interaction.guild,
            self.values[0].id,
        )
        if channel is None:
            await interaction.response.send_message(
                error or "Invalid channel.",
                ephemeral=True,
            )
            return

        try:
            async with SessionFactory() as session:
                await set_event_channel(
                    session,
                    self.manager.guild_id,
                    self.manager.selected_target,
                    str(channel.id),
                )
                await session.commit()
            await refresh_guild_summary_messages(self.manager.guild_id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.edit_message(
            content=await self.manager.content(
                notice=f"Channel updated to {channel.mention}.",
            ),
            view=self.manager,
        )


class ChannelManagerButton(discord.ui.Button):
    def __init__(
        self,
        manager: ChannelManagerView,
        action: str,
        label: str,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ) -> None:
        self.manager = manager
        self.action = action
        super().__init__(label=label, style=style, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.manager.handle_action(interaction, self.action)


class ChannelManagerView(discord.ui.View):
    def __init__(
        self,
        *,
        invoker_id: int,
        guild_id: str,
        leagues: list[GuildLeague],
        default_league_id: str | None,
    ) -> None:
        super().__init__(timeout=600)
        self.invoker_id = invoker_id
        self.guild_id = guild_id
        self.leagues = leagues
        self.default_league_id = default_league_id
        self.selected_target = "default"
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(
            "Only the administrator who opened this setup can use these controls.",
            ephemeral=True,
        )
        return False

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(ChannelTargetSelect(self))
        self.add_item(ChannelPicker(self))
        self.add_item(
            ChannelManagerButton(
                self,
                "clear",
                "Clear Channel",
                discord.ButtonStyle.danger,
            )
        )
        self.add_item(ChannelManagerButton(self, "back", "Back"))

    async def content(self, notice: str | None = None) -> str:
        try:
            async with SessionFactory() as session:
                league, channel_id = await resolve_event_channel(
                    session,
                    self.guild_id,
                    self.selected_target,
                )
                await session.commit()
            label = (
                "All non-default Leagues"
                if self.selected_target == "all"
                else league.name if league is not None else self.selected_target
            )
        except ValueError:
            channel_id = None
            label = self.selected_target

        current = f"<#{channel_id}>" if channel_id else "Not configured"
        lines = [
            "## 📣 Announcement Channels",
            f"**Target:** {label}",
            f"**Current/effective channel:** {current}",
            "",
            "Choose a text channel below, clear the current setting, or select another target.",
        ]
        if notice:
            lines.extend(["", f"**{notice}**"])
        return "\n".join(lines)

    async def handle_action(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "clear":
            try:
                async with SessionFactory() as session:
                    await clear_event_channel(
                        session,
                        self.guild_id,
                        self.selected_target,
                    )
                    await session.commit()
                await refresh_guild_summary_messages(self.guild_id)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            await interaction.response.edit_message(
                content=await self.content(notice="Channel setting cleared."),
                view=self,
            )
            return

        if action == "back":
            view = SetupDashboardView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
            )
            await interaction.response.edit_message(
                content=await _setup_dashboard_content(self.guild_id),
                view=view,
            )


class PostTargetSelect(discord.ui.Select):
    def __init__(self, tools: PostToolsView) -> None:
        self.tools = tools
        options = [
            discord.SelectOption(
                label="Default League",
                value="default",
                default=tools.selected_target == "default",
            ),
            discord.SelectOption(
                label="All non-default Leagues",
                value="all",
                default=tools.selected_target == "all",
            ),
        ]
        options.extend(
            discord.SelectOption(
                label=league.name[:100],
                value=league.league_id,
                default=tools.selected_target == league.league_id,
            )
            for league in tools.leagues
        )
        super().__init__(
            placeholder="Choose which events to work with",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.tools.selected_target = self.values[0]
        self.tools.rebuild()
        await interaction.response.edit_message(
            content=self.tools.content(),
            view=self.tools,
        )


class PostToolsButton(discord.ui.Button):
    def __init__(
        self,
        tools: PostToolsView,
        action: str,
        label: str,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ) -> None:
        self.tools = tools
        self.action = action
        super().__init__(label=label, style=style, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.tools.handle_action(interaction, self.action)


class PostToolsView(discord.ui.View):
    def __init__(
        self,
        *,
        invoker_id: int,
        guild_id: str,
        leagues: list[GuildLeague],
    ) -> None:
        super().__init__(timeout=600)
        self.invoker_id = invoker_id
        self.guild_id = guild_id
        self.leagues = leagues
        self.selected_target = "default"
        self.notice: str | None = None
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.invoker_id:
            return True
        await interaction.response.send_message(
            "Only the administrator who opened this setup can use these controls.",
            ephemeral=True,
        )
        return False

    def target_label(self) -> str:
        if self.selected_target == "default":
            return "Default League"
        if self.selected_target == "all":
            return "All non-default Leagues"
        for league in self.leagues:
            if league.league_id == self.selected_target:
                return league.name
        return self.selected_target

    def content(self) -> str:
        lines = [
            "## 🧪 Event Post Tools",
            f"**Target:** {self.target_label()}",
            "",
            "**Test Post** sends one preview without creating a discussion thread.",
            "**Backfill** publishes already-known events as full cards with threads.",
        ]
        if self.notice:
            lines.extend(["", f"**{self.notice}**"])
        return "\n".join(lines)

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(PostTargetSelect(self))
        self.add_item(
            PostToolsButton(
                self,
                "test",
                "Test Post",
                discord.ButtonStyle.primary,
            )
        )
        self.add_item(PostToolsButton(self, "backfill3", "Backfill 3"))
        self.add_item(PostToolsButton(self, "backfill5", "Backfill 5"))
        self.add_item(PostToolsButton(self, "backfill10", "Backfill 10"))
        self.add_item(PostToolsButton(self, "back", "Back"))

    async def handle_action(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        if action == "back":
            view = SetupDashboardView(
                invoker_id=self.invoker_id,
                guild_id=self.guild_id,
            )
            await interaction.response.edit_message(
                content=await _setup_dashboard_content(self.guild_id),
                view=view,
            )
            return

        if action == "test":
            try:
                channel, event, league_name = await _preview_event_target(
                    self.guild_id,
                    self.selected_target,
                )
                await channel.send(
                    embed=_event_embed(event, league_name, preview=True),
                    view=_event_link_view(event),
                )
            except ValueError as exc:
                self.notice = str(exc)
            else:
                self.notice = f"Test card sent to {channel.mention}."
            self.rebuild()
            await interaction.response.edit_message(
                content=self.content(),
                view=self,
            )
            return

        count = {
            "backfill3": 3,
            "backfill5": 5,
            "backfill10": 10,
        }.get(action)
        if count is None:
            return

        try:
            posted = await _backfill_target(
                self.guild_id,
                self.selected_target,
                count,
            )
            await refresh_guild_summary_messages(self.guild_id)
        except ValueError as exc:
            self.notice = str(exc)
        else:
            self.notice = f"Published {posted} existing event card(s)."

        self.rebuild()
        await interaction.response.edit_message(
            content=self.content(),
            view=self,
        )


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
                "## PokÈvent setup · 2/4\n"
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
                    "## PokÈvent setup · 3/4\n"
                    f"Default League: **{self._league_name()}**\n"
                    f"Default channel: {channel.mention}\n\n"
                    "What should PokEvent do with your **other configured Leagues**? "
                    "You can still give individual Leagues their own channel later from **Channels**."
                ),
                view=self,
            )
            return

        self.all_channel_id = str(channel.id)
        self.show_backfill_step()
        await interaction.response.edit_message(
            content=(
                "## PokÈvent setup · 4/4\n"
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
                    "## PokÈvent setup · 3/4\n"
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
                "## PokÈvent setup · 4/4\n"
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

        dashboard = SetupDashboardView(
            invoker_id=self.invoker_id,
            guild_id=self.guild_id,
        )
        await interaction.edit_original_response(
            content=await _setup_dashboard_content(
                self.guild_id,
                notice=(
                    "Guided setup complete · "
                    f"{posted} existing full event card(s) posted."
                ),
            ),
            view=dashboard,
        )
        self.stop()


@pokevent.command(name="status", description="Show the PokÈvent service status.")
async def status(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        f"PokÈvent {__version__} is online.",
        ephemeral=True,
    )


@pokevent.command(
    name="setup",
    description="Open the PokÈvent setup and administration dashboard.",
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
        dashboard = SetupDashboardView(
            invoker_id=interaction.user.id,
            guild_id=guild_id,
        )
        await interaction.response.send_message(
            await _setup_dashboard_content(
                guild_id,
                notice="Add a League to begin setup.",
            ),
            view=dashboard,
            ephemeral=True,
        )
        return

    if config.default_league_id and config.default_channel_id:
        dashboard = SetupDashboardView(
            invoker_id=interaction.user.id,
            guild_id=guild_id,
        )
        await interaction.response.send_message(
            await _setup_dashboard_content(guild_id),
            view=dashboard,
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
        "## PokÈvent setup · 1/4\n"
        "Choose this server's **default League**. This is what /events shows "
        "when no League is specified.\n\n"
        f"{league_lines}\n\n"
        "-# You can manage additional Leagues from this dashboard after setup.",
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
                    "A server administrator can configure one with /pokevent setup.",
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

    resolved_channel, error = await _validate_announcement_channel(
        interaction.guild,
        channel.id,
    )
    if resolved_channel is None:
        await _send_error(interaction, error or "Invalid announcement channel.")
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
                league_ids = [
                    route.upstream_organisation_id
                    for route in routes
                    if route.upstream_organisation_id is not None
                ]
                statement = (
                    select(Event)
                    .where(
                        Event.starts_at >= datetime.now(UTC),
                        Event.status == "active",
                        Event.upstream_organisation_id.in_(league_ids),
                    )
                    .order_by(Event.starts_at)
                    .limit(1)
                )
                league_name = None
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
            if event is not None and league_name is None:
                configured = await session.scalar(
                    select(GuildLeague).where(
                        GuildLeague.guild_id == guild_id,
                        GuildLeague.league_id == event.upstream_organisation_id,
                    )
                )
                league_name = configured.name if configured is not None else None
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
            "You need the Administrator permission to change PokÈvent configuration.",
        )
        return
    raise error


bot.tree.add_command(pokevent)


async def run_bot() -> None:
    if not settings.discord_token:
        raise RuntimeError("POKEVENT_DISCORD_TOKEN is required to run the Discord bot.")
    await bot.start(settings.discord_token)


def main() -> None:
    asyncio.run(run_bot())

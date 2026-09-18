from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from . import __version__
from .config import get_settings
from .db import SessionFactory
from .models import Event

settings = get_settings()

EVENTS_PAGE_SIZE = 10
EVENTS_QUERY_LIMIT = 250


class PokEventBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

    async def setup_hook(self) -> None:
        await self.tree.sync()


def _event_line(event: Event) -> str:
    title = event.title
    if len(title) > 120:
        title = f"{title[:117]}..."
    return f"**{title}** — {discord.utils.format_dt(event.starts_at, style='F')}"


def event_page_content(rows: list[Event], page: int) -> str:
    total_pages = max(1, math.ceil(len(rows) / EVENTS_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    start = page * EVENTS_PAGE_SIZE
    visible = rows[start : start + EVENTS_PAGE_SIZE]

    lines = [_event_line(event) for event in visible]
    lines.append("")
    lines.append(
        f"Page **{page + 1}/{total_pages}** · "
        f"Showing {start + 1}-{start + len(visible)} of {len(rows)} upcoming events"
    )
    return "\n".join(lines)


class EventPagerView(discord.ui.View):
    def __init__(self, rows: list[Event]) -> None:
        super().__init__(timeout=180)
        self.rows = rows
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
            content=event_page_content(self.rows, self.page),
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
            content=event_page_content(self.rows, self.page),
            view=self,
        )


bot = PokEventBot()
pokevent = app_commands.Group(name="pokevent", description="PokEvent 3.0")


@pokevent.command(name="status", description="Show the PokEvent service status.")
async def status(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        f"PokEvent {__version__} is online.",
        ephemeral=True,
    )


@bot.tree.command(name="events", description="Browse upcoming Pokémon events.")
async def events(interaction: discord.Interaction) -> None:
    now = datetime.now(UTC)
    async with SessionFactory() as session:
        rows = list(
            (
                await session.scalars(
                    select(Event)
                    .where(Event.starts_at >= now, Event.status == "active")
                    .order_by(Event.starts_at)
                    .limit(EVENTS_QUERY_LIMIT)
                )
            ).all()
        )

    if not rows:
        await interaction.response.send_message(
            "No upcoming events are currently in the PokEvent catalogue.",
            ephemeral=True,
        )
        return

    view = EventPagerView(rows)
    await interaction.response.send_message(
        event_page_content(rows, 0),
        view=view,
        ephemeral=True,
    )


bot.tree.add_command(pokevent)


async def run_bot() -> None:
    if not settings.discord_token:
        raise RuntimeError("POKEVENT_DISCORD_TOKEN is required to run the Discord bot.")
    await bot.start(settings.discord_token)


def main() -> None:
    asyncio.run(run_bot())

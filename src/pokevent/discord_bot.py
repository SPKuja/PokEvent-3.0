from __future__ import annotations

import asyncio
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


class PokEventBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

    async def setup_hook(self) -> None:
        await self.tree.sync()


bot = PokEventBot()
pokevent = app_commands.Group(name="pokevent", description="PokEvent 3.0")


@pokevent.command(name="status", description="Show the PokEvent service status.")
async def status(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        f"PokEvent {__version__} is online.",
        ephemeral=True,
    )


@bot.tree.command(name="events", description="Show the next Pokémon events in the catalogue.")
async def events(interaction: discord.Interaction) -> None:
    now = datetime.now(UTC)
    async with SessionFactory() as session:
        rows = (
            await session.scalars(
                select(Event)
                .where(Event.starts_at >= now, Event.status == "active")
                .order_by(Event.starts_at)
                .limit(10)
            )
        ).all()

    if not rows:
        await interaction.response.send_message(
            "No upcoming events are currently in the PokEvent catalogue.",
            ephemeral=True,
        )
        return

    lines = [
        f"**{event.title}** — {discord.utils.format_dt(event.starts_at, style='F')}"
        for event in rows
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


bot.tree.add_command(pokevent)


async def run_bot() -> None:
    if not settings.discord_token:
        raise RuntimeError("POKEVENT_DISCORD_TOKEN is required to run the Discord bot.")
    await bot.start(settings.discord_token)


def main() -> None:
    asyncio.run(run_bot())

# PokEvent 3.0

PokEvent 3.0 is a community-first Pokémon event discovery and publishing platform.

Play! Pokémon is the primary event source. PokEvent normalises events into one
local catalogue, then publishes that catalogue to Discord, a public web/API
surface and subscribable iCalendar feeds.

## Why 3.0

PokEvent 3.0 removes Facebook from the event pipeline. Discord is no longer the
database either: it is one output of the central catalogue.

A Discord server can route:

- one League / Activity Group to one channel;
- one Play! Pokémon location/store to one channel;
- a game such as TCG, VGC or GO;
- all matching events inside a geographic radius.

This lets a League route its own events to one channel while a wider community
server can surface every sanctioned event around Swindon.

## Current status

The 3.0 foundation is in active development.

Implemented in the foundation:

- normalised event, organisation, guild, route and published-message schema;
- stable upstream IDs kept separately from PokEvent-owned IDs;
- pure routing engine for organisation, location, game and distance;
- Discord bot bootstrap with `/events` and `/pokevent status`;
- FastAPI health/event API;
- public iCalendar feed;
- PostgreSQL Docker deployment;
- Alembic migrations;
- isolated Play! Pokémon source adapter.

The Play! Pokémon ingestion adapter is intentionally not scraping the rendered
Event Locator. Its underlying event data interface and stable organisation /
location identifiers need to be verified first.

## Development

Copy the environment file:

```bash
cp .env.example .env
```

For local SQLite development:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
pytest
pokevent-web
```

Run the Discord bot separately after adding a Discord token:

```bash
pokevent-bot
```

## Docker / Portainer

Set a strong `POSTGRES_PASSWORD` and `POKEVENT_DISCORD_TOKEN` in `.env`, then:

```bash
docker compose up -d --build
```

The stack starts PostgreSQL, runs database migrations once, then starts the web
and bot services.

## Architecture

See [docs/architecture.md](docs/architecture.md).

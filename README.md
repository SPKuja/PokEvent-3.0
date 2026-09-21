# PokÈvent 3.0

PokÈvent 3.0 is a community-first Pokémon event discovery and publishing platform.

Play! Pokémon is the authority for event identity. PokÈvent builds one
normalised local catalogue, then publishes that catalogue to Discord, a public
web/API surface and subscribable iCalendar feeds.

## Why 3.0

PokÈvent 3.0 removes Facebook from the event pipeline. Discord is no longer the
database either: it is one output of the central catalogue.

The goal is full local-community coverage: TCG, VGC and Pokémon GO; Cups,
Challenges, Prereleases, normal League sessions and friendly listings.

A Discord server can route events by stable Play! Pokémon League ID, game and
other rules. Server owners do not need to configure geographic coordinates.

For example:

```env
POKEVENT_LEAGUES={"2012924":"Pokémon League Swindon"}
```

League `2012924` remains the identity even when its event is hosted at a
different venue.

## Current status

Implemented:

- normalised event, organisation, guild, route and published-message schema;
- stable upstream event and League identifiers;
- complete API-v2 event ingestion over a bounded country/date window;
- TCG / VGC / GO classification;
- premier, Prerelease and League/friendly coverage;
- preservation of unknown future event types;
- explicit League-ID registry;
- local geographic discovery for other nearby Leagues;
- content hashing and catalogue updates;
- background sync worker;
- Discord bot bootstrap with `/events` and `/pokevent status`;
- FastAPI health/event API;
- public iCalendar feed;
- PostgreSQL Docker deployment;
- Alembic migrations;
- CI quality gate.

The rendered official Event Locator is not scraped. PokÈvent uses structured
mirrored Play! Pokémon records and keeps the upstream source adapter isolated.

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

Run the event synchroniser separately:

```bash
pokevent-worker
```

## Docker / Portainer

Set a strong `POSTGRES_PASSWORD` and `POKEVENT_DISCORD_TOKEN` in `.env`, then:

```bash
docker compose up -d --build
```

The stack starts PostgreSQL, runs database migrations once, then starts the web,
Discord bot and event-sync worker services.

## Architecture

See [docs/architecture.md](docs/architecture.md) and
[docs/event-source-research.md](docs/event-source-research.md).

## Portainer deployment

For Portainer, use the dedicated `docker-compose.portainer.yml` file. It pulls
the tested `ghcr.io/spkuja/pokevent-3.0:latest` image instead of rebuilding the
application from Git.

The app services use `pull_policy: always`, so redeploying/updating the stack
checks GitHub Container Registry for the newest green `main` image. Database
migrations run before the web, bot and worker services start.

Required variables:

- `POSTGRES_PASSWORD` — strong database password;
- `POKEVENT_DISCORD_TOKEN` — Discord bot token.

Recommended variables:

- `POKEVENT_PUBLIC_BASE_URL` — public HTTPS URL once reverse proxying is set up;
- `POKEVENT_LEAGUES` — JSON map of the default League IDs and friendly names
  monitored by PokÈvent. Keep this in Portainer so new default Leagues can be
  added without changing or rebuilding the application;
- `POKEVENT_ENABLE_MEMBER_WELCOMES` — enables Discord member-join events for
  configured welcome messages. The Portainer stack defaults this to `true`.
  The bot must also have **Server Members Intent** enabled in the Discord
  Developer Portal.

Most other PokÈvent settings already have application defaults and only need to
be added to Portainer when overriding those defaults.

The web service joins the external `NeuralNet` Docker network and uses the
stable container/network name `pokevent-web`. Nginx Proxy Manager should proxy
to `pokevent-web` on port `8080`. PostgreSQL remains on the stack's private
default network.

The CI workflow publishes `:latest` only after the test job passes on `main`.
Version tags beginning with `v` are also published as matching container tags,
which allows a deployment to be pinned to a specific release if desired.

## Bot information

- `GET /bot` shows live PokÈvent Discord bot information, uptime, server count and invite link.
- `GET /api/bot` returns the same bot runtime information as JSON.


## Public web pages

- `GET /` — configured-League calendar and list view.
- Official Play! Pokémon Event Locator — https://events.pokemon.com/EventLocator/?locale=en-us — use Pokémon's locator for broader event discovery outside PokÈvent's configured League calendar.
- `GET /bot` — live Discord bot status, uptime, server count, invite link and command reference.


The `/pokevent setup` admin dashboard includes **Check New Events**, which runs an immediate source sync, publishes any genuinely new routed events and refreshes the server's rolling summaries.

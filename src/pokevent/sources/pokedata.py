from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from pokevent.domain import EventSearch, EventSnapshot, EventStatus, Game
from pokevent.routing import distance_miles

from .base import EventSource, EventSourceError

POKEDATA_API_V2 = "https://pokedata.ovh/events/apiv2"
MIN_COMPLETE_SHARE = 0.95

def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _parse_wall_datetime(value: Any, timezone: tzinfo) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed


def _product_games(raw: dict[str, Any]) -> set[Game]:
    product = (
        _text(raw.get("product"))
        or _text(raw.get("Products"))
        or ""
    ).lower()

    games: set[Game] = set()
    for token in (part.strip() for part in product.split(",")):
        if token == "tcg":
            games.add(Game.TCG)
        elif token in {"vg", "vgc", "video game"}:
            games.add(Game.VGC)
        elif token in {"go", "pgo", "pokemon go"}:
            games.add(Game.GO)
    return games


def _game(raw: dict[str, Any]) -> Game:
    event_type = (_text(raw.get("type")) or "").lower()

    if "nonpremier tcg" in event_type:
        return Game.TCG
    if "nonpremier vg" in event_type or "nonpremier vgc" in event_type:
        return Game.VGC
    if "nonpremier go" in event_type:
        return Game.GO

    games = _product_games(raw)
    if len(games) == 1:
        return next(iter(games))

    return Game.OTHER


def _status(raw: dict[str, Any]) -> EventStatus:
    value = (_text(raw.get("Status")) or _text(raw.get("status")) or "").lower()
    if any(word in value for word in ("cancel", "deleted", "removed")):
        return EventStatus.CANCELLED
    return EventStatus.ACTIVE


def _is_unnamed_friendly(raw: dict[str, Any]) -> bool:
    raw_type = (
        _text(raw.get("type"))
        or _text(raw.get("Subtype"))
        or ""
    ).lower()
    name = _text(raw.get("Name")) or _text(raw.get("name"))
    return raw_type.startswith("nonpremier ") and not name


def _event_type(raw: dict[str, Any]) -> str | None:
    raw_type = _text(raw.get("type")) or _text(raw.get("Subtype"))
    if not raw_type:
        return None

    if raw_type.lower().startswith("nonpremier "):
        if _is_unnamed_friendly(raw):
            return "League Session"
        return "Friendly Tournament"

    return raw_type


def _starts_at(raw: dict[str, Any], local_timezone: ZoneInfo) -> datetime:
    start = _parse_iso_datetime(raw.get("Start_date"))
    if start is not None:
        if start.tzinfo is None:
            return start.replace(tzinfo=local_timezone)
        return start

    # Pokedata's unnamed local/League rows historically expose UTC in "when".
    # Named listings use venue wall time.
    timezone: tzinfo = UTC if _is_unnamed_friendly(raw) else local_timezone
    fallback = _parse_wall_datetime(raw.get("when"), timezone)
    if fallback is None:
        guid = _text(raw.get("guid")) or _text(raw.get("Guid")) or "unknown"
        raise EventSourceError(f"Pokedata event {guid} has no parseable start time")
    return fallback


def parse_pokedata_event(
    raw: dict[str, Any],
    *,
    local_timezone: str = "Europe/London",
) -> EventSnapshot:
    """Normalise one Play! Pokemon event mirrored by Pokedata API v2."""

    guid = _text(raw.get("guid")) or _text(raw.get("Guid"))
    if not guid:
        raise EventSourceError("Pokedata event is missing guid/Guid")

    try:
        timezone = ZoneInfo(local_timezone)
    except Exception as exc:
        raise EventSourceError(f"Invalid event timezone {local_timezone!r}") from exc

    event_type = _event_type(raw)
    shop = _text(raw.get("shop"))
    title = (
        _text(raw.get("Name"))
        or _text(raw.get("name"))
        or " - ".join(part for part in (shop, event_type) if part)
        or "Play! Pokemon event"
    )

    registration_url = (
        _text(raw.get("Third_party_registration_website"))
        or _text(raw.get("Event_website"))
    )

    return EventSnapshot(
        source="pokedata",
        upstream_event_id=guid,
        upstream_organisation_id=_text(raw.get("league")),
        title=title,
        game=_game(raw),
        event_type=event_type,
        status=_status(raw),
        starts_at=_starts_at(raw, timezone),
        organisation_name=shop,
        venue_name=shop,
        address=_text(raw.get("street_address")),
        city=_text(raw.get("city")),
        postcode=_text(raw.get("postal_code")),
        country=_text(raw.get("country_code")),
        latitude=_float(raw.get("latitude")),
        longitude=_float(raw.get("longitude")),
        source_url=_text(raw.get("pokemon_url")),
        registration_url=registration_url,
        upstream_payload=raw,
    )


class PokedataSource(EventSource):
    """Paginated API-v2 mirror of Play! Pokemon events.

    API v2's country and date filters are used upstream. Its documented radius
    filter currently returns empty data for valid searches, so Pokevent applies
    geographic filtering locally. Configured League IDs are always retained,
    even when their event is outside the community discovery radius.
    """

    name = "pokedata"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        attempts: int = 4,
        delay_seconds: float = 0.15,
        country_code: str = "GB",
        local_timezone: str = "Europe/London",
        horizon_days: int = 90,
        monitored_league_ids: set[str] | None = None,
    ) -> None:
        self._client = client
        self.attempts = attempts
        self.delay_seconds = delay_seconds
        self.country_code = country_code.upper()
        self.local_timezone = local_timezone
        self.horizon_days = horizon_days
        self.monitored_league_ids = monitored_league_ids or set()

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
        }

    def query_url(self, search: EventSearch, page: int) -> str:
        start = (
            search.starts_after.date()
            if search.starts_after
            else datetime.now(UTC).date()
        )
        end = start + timedelta(days=self.horizon_days)
        country = quote(self.country_code, safe="")

        return (
            f"{POKEDATA_API_V2}"
            f"/_country/{country}"
            f"/_start/{start.isoformat()}"
            f"/_end/{end.isoformat()}"
            f"/_page/{page}"
        )

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        search: EventSearch,
        page: int,
    ) -> tuple[list[dict[str, Any]], int, int]:
        last_error: Exception | None = None

        for attempt in range(1, self.attempts + 1):
            try:
                response = await client.get(
                    self.query_url(search, page),
                    headers=self._headers(),
                )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise EventSourceError(
                        f"Pokedata page {page} returned an unexpected root shape"
                    )

                metadata = body.get("metadata")
                events = body.get("events")
                if not isinstance(metadata, dict) or not isinstance(events, list):
                    raise EventSourceError(
                        f"Pokedata page {page} returned an unexpected response shape"
                    )

                total_items = metadata.get("total_items")
                total_pages = metadata.get("total_pages")
                current_page = metadata.get("current_page")
                if not all(
                    isinstance(value, int) and value >= 0
                    for value in (total_items, total_pages, current_page)
                ):
                    raise EventSourceError(
                        f"Pokedata page {page} returned invalid pagination metadata"
                    )
                if current_page != page:
                    raise EventSourceError(
                        f"Pokedata returned page {current_page} when {page} was requested"
                    )

                rows = [event for event in events if isinstance(event, dict)]
                return rows, total_items, total_pages
            except (httpx.HTTPError, ValueError, EventSourceError) as exc:
                last_error = exc
                if attempt < self.attempts:
                    await asyncio.sleep(2 ** (attempt - 1))

        raise EventSourceError(
            f"Pokedata page {page} failed after {self.attempts} attempts: {last_error}"
        )

    async def _fetch_all_raw(
        self,
        client: httpx.AsyncClient,
        search: EventSearch,
    ) -> list[dict[str, Any]]:
        first, total_items, total_pages = await self._fetch_page(client, search, 1)
        if total_pages == 0:
            return []

        events = list(first)

        for page in range(2, total_pages + 1):
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)

            rows, next_total, next_pages = await self._fetch_page(
                client,
                search,
                page,
            )
            if next_total != total_items or next_pages != total_pages:
                raise EventSourceError(
                    "Pokedata pagination changed while the catalogue was being fetched"
                )
            events.extend(rows)

        distinct_ids = {
            _text(event.get("guid")) or _text(event.get("Guid"))
            for event in events
            if _text(event.get("guid")) or _text(event.get("Guid"))
        }
        if total_items and len(distinct_ids) < total_items * MIN_COMPLETE_SHARE:
            raise EventSourceError(
                f"Pokedata returned {len(distinct_ids)} distinct events "
                f"from {total_items} advertised"
            )

        return events

    def _keep_event(self, event: EventSnapshot, search: EventSearch) -> bool:
        league_id = event.upstream_organisation_id
        if league_id and league_id in self.monitored_league_ids:
            return True

        if event.latitude is None or event.longitude is None:
            return False

        return (
            distance_miles(
                search.latitude,
                search.longitude,
                event.latitude,
                event.longitude,
            )
            <= search.radius_miles
        )

    async def fetch_events(self, search: EventSearch) -> list[EventSnapshot]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=45)

        try:
            raw_events = await self._fetch_all_raw(client, search)
        finally:
            if owns_client:
                await client.aclose()

        results: list[EventSnapshot] = []
        for raw in raw_events:
            try:
                event = parse_pokedata_event(
                    raw,
                    local_timezone=self.local_timezone,
                )
            except EventSourceError:
                continue

            if search.starts_after and event.starts_at < search.starts_after:
                continue
            if not self._keep_event(event, search):
                continue

            results.append(event)

        return sorted(results, key=lambda event: event.starts_at)

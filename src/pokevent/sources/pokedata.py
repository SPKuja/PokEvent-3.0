from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from pokevent.domain import EventSearch, EventSnapshot, EventStatus, Game
from pokevent.routing import distance_miles

from .base import EventSource, EventSourceError

POKEDATA_LEGACY_API = "https://pokedata.ovh/events/api"
POKEDATA_TABLE_API = "https://www.pokedata.ovh/events/tableapi/"
TABLE_PAGE_SIZE = 100
TABLE_PAGE_LIMIT = 100

REGIONAL_STREAMS: tuple[tuple[Game, str], ...] = (
    (Game.TCG, "_tcg/cups/challenges/pre"),
    (Game.VGC, "_vg/cups/challenges"),
    (Game.GO, "_go/cups/challenges"),
)

FRIENDLY_TYPE_NAMES = {
    "nonpremier tcg": "League / Friendly",
    "nonpremier vg": "League / Friendly",
    "nonpremier vgc": "League / Friendly",
    "nonpremier go": "League / Friendly",
}


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


def _game(raw: dict[str, Any], game_hint: Game | None = None) -> Game:
    if game_hint is not None:
        return game_hint

    product = (
        _text(raw.get("Products"))
        or _text(raw.get("product"))
        or ""
    ).lower()
    event_type = (_text(raw.get("type")) or "").lower()

    if product == "tcg" or "tcg" in event_type:
        return Game.TCG
    if product in {"vg", "vgc", "video game"} or any(
        token in event_type for token in (" vgc", " vg", "video game")
    ):
        return Game.VGC
    if product in {"go", "pokemon go"} or "pokemon go" in event_type or event_type.endswith(" go"):
        return Game.GO
    return Game.OTHER


def _status(raw: dict[str, Any]) -> EventStatus:
    value = (_text(raw.get("Status")) or _text(raw.get("status")) or "").lower()
    if any(word in value for word in ("cancel", "deleted", "removed")):
        return EventStatus.CANCELLED
    return EventStatus.ACTIVE


def _is_unnamed_friendly(raw: dict[str, Any]) -> bool:
    name = _text(raw.get("Name")) or _text(raw.get("name"))
    pokemon_url = _text(raw.get("pokemon_url")) or ""
    return not name and pokemon_url.rstrip("/").endswith("play-pokemon-tournaments")


def _starts_at(
    raw: dict[str, Any],
    *,
    local_timezone: ZoneInfo,
    table_friendly: bool,
) -> datetime:
    start = _parse_iso_datetime(raw.get("Start_date"))
    if start is not None:
        if start.tzinfo is None:
            return start.replace(tzinfo=local_timezone)
        return start

    # Pokedata's unnamed friendly/table rows use UTC in when; named rows
    # and the regional sanctioned feed use venue wall time.
    timezone: tzinfo = UTC if table_friendly and _is_unnamed_friendly(raw) else local_timezone
    fallback = _parse_wall_datetime(raw.get("when"), timezone)
    if fallback is None:
        guid = _text(raw.get("guid")) or _text(raw.get("Guid")) or "unknown"
        raise EventSourceError(f"Pokedata event {guid} has no parseable start time")
    return fallback


def parse_pokedata_event(
    raw: dict[str, Any],
    *,
    game_hint: Game | None = None,
    local_timezone: str = "Europe/London",
    table_friendly: bool = False,
) -> EventSnapshot:
    """Normalise one Play! Pokemon event mirrored by Pokedata."""

    guid = _text(raw.get("guid")) or _text(raw.get("Guid"))
    if not guid:
        raise EventSourceError("Pokedata event is missing guid/Guid")

    try:
        timezone = ZoneInfo(local_timezone)
    except Exception as exc:
        raise EventSourceError(f"Invalid event timezone {local_timezone!r}") from exc

    starts_at = _starts_at(
        raw,
        local_timezone=timezone,
        table_friendly=table_friendly,
    )

    raw_type = _text(raw.get("type")) or _text(raw.get("Subtype"))
    event_type = FRIENDLY_TYPE_NAMES.get((raw_type or "").lower(), raw_type)
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
        game=_game(raw, game_hint),
        event_type=event_type,
        status=_status(raw),
        starts_at=starts_at,
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
    """Structured mirror/fallback covering sanctioned and friendly Play! events."""

    name = "pokedata"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        attempts: int = 4,
        country_code: str = "GB",
        local_timezone: str = "Europe/London",
        friendly_horizon_days: int = 45,
    ) -> None:
        self._client = client
        self.attempts = attempts
        self.country_code = country_code.upper()
        self.local_timezone = local_timezone
        self.friendly_horizon_days = friendly_horizon_days

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
        }

    @staticmethod
    def regional_url(path: str, search: EventSearch) -> str:
        start = (
            search.starts_after.date()
            if search.starts_after
            else datetime.now(UTC).date()
        )
        return (
            f"{POKEDATA_LEGACY_API}/{path}"
            f"/_latitude/{search.latitude}"
            f"/_longitude/{search.longitude}"
            f"/_radius/{search.radius_miles}"
            f"/_unit/mi/_start/{start.isoformat()}"
        )

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        *,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    headers={
                        **self._headers(),
                        **({"Content-Type": "application/json"} if json_body else {}),
                    },
                    json=json_body,
                )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < self.attempts:
                    await asyncio.sleep(2 ** (attempt - 1))

        raise EventSourceError(
            f"Pokedata request failed after {self.attempts} attempts: {last_error}"
        )

    async def _fetch_regional(
        self,
        client: httpx.AsyncClient,
        search: EventSearch,
    ) -> list[tuple[dict[str, Any], Game, bool]]:
        combined: list[tuple[dict[str, Any], Game, bool]] = []

        for game, path in REGIONAL_STREAMS:
            body = await self._request_json(
                client,
                method="GET",
                url=self.regional_url(path, search),
            )
            if not isinstance(body, list):
                raise EventSourceError(
                    f"Pokedata {game.value} regional feed returned an unexpected shape"
                )
            combined.extend(
                (row, game, False)
                for row in body
                if isinstance(row, dict)
            )

        return combined

    def _friendly_query(self, page: int) -> dict[str, Any]:
        return {
            "past": "",
            "country": self.country_code,
            "city": "",
            "shop": "",
            "league": "",
            "states": "[]",
            "postcode": "",
            "cups": "",
            "challenges": "",
            "vcups": "",
            "vchallenges": "",
            "prereleases": "",
            "premier": "",
            "go": "",
            "gocup": "",
            "mss": "",
            "ftcg": "1",
            "fvg": "1",
            "fgo": "1",
            "latitude": "",
            "longitude": "",
            "radius": "",
            "unit": "mi",
            "width": 1400,
            "page": page,
        }

    @staticmethod
    def _row_date(row: dict[str, Any]) -> date | None:
        raw = _text(row.get("date"))
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None

    async def _fetch_friendlies(
        self,
        client: httpx.AsyncClient,
        search: EventSearch,
    ) -> list[tuple[dict[str, Any], Game | None, bool]]:
        if search.starts_after:
            start_date = search.starts_after.date()
        else:
            start_date = datetime.now(UTC).date()
        cutoff = start_date + timedelta(days=self.friendly_horizon_days)

        combined: list[tuple[dict[str, Any], Game | None, bool]] = []
        previous_last: date | None = None

        for page in range(TABLE_PAGE_LIMIT):
            body = await self._request_json(
                client,
                method="POST",
                url=POKEDATA_TABLE_API,
                json_body=self._friendly_query(page),
            )
            if not isinstance(body, list):
                raise EventSourceError(
                    f"Pokedata friendly page {page} returned an unexpected shape"
                )

            rows = [row for row in body if isinstance(row, dict)]
            if not rows:
                return combined

            first_date = self._row_date(rows[0])
            last_date = self._row_date(rows[-1])
            if (
                previous_last is not None
                and first_date is not None
                and first_date < previous_last
            ):
                raise EventSourceError(
                    "Pokedata friendly feed is no longer sorted by date"
                )
            if last_date is not None:
                previous_last = last_date

            for row in rows:
                row_date = self._row_date(row)
                if row_date is None or row_date < start_date or row_date > cutoff:
                    continue
                combined.append((row, None, True))

            if len(rows) < TABLE_PAGE_SIZE or (
                last_date is not None and last_date > cutoff
            ):
                return combined

        raise EventSourceError(
            f"Pokedata friendly feed exceeded {TABLE_PAGE_LIMIT} pages"
        )

    @staticmethod
    def _deduplicate(
        rows: list[tuple[dict[str, Any], Game | None, bool]],
    ) -> list[tuple[dict[str, Any], Game | None, bool]]:
        seen: set[str] = set()
        unique: list[tuple[dict[str, Any], Game | None, bool]] = []

        for raw, game_hint, table_friendly in rows:
            guid = _text(raw.get("guid")) or _text(raw.get("Guid"))
            if not guid or guid in seen:
                continue
            seen.add(guid)
            unique.append((raw, game_hint, table_friendly))

        return unique

    async def fetch_events(self, search: EventSearch) -> list[EventSnapshot]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=60)
        try:
            regional, friendlies = await asyncio.gather(
                self._fetch_regional(client, search),
                self._fetch_friendlies(client, search),
            )
        finally:
            if owns_client:
                await client.aclose()

        results: list[EventSnapshot] = []
        for raw, game_hint, table_friendly in self._deduplicate(regional + friendlies):
            try:
                event = parse_pokedata_event(
                    raw,
                    game_hint=game_hint,
                    local_timezone=self.local_timezone,
                    table_friendly=table_friendly,
                )
            except EventSourceError:
                continue

            if search.starts_after and event.starts_at < search.starts_after:
                continue

            if event.latitude is not None and event.longitude is not None:
                if (
                    distance_miles(
                        search.latitude,
                        search.longitude,
                        event.latitude,
                        event.longitude,
                    )
                    > search.radius_miles
                ):
                    continue
            elif table_friendly:
                continue

            results.append(event)

        return sorted(results, key=lambda event: event.starts_at)

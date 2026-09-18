from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from pokevent.domain import EventSearch, EventSnapshot, EventStatus, Game
from pokevent.routing import distance_miles

from .base import EventSource, EventSourceError

POKEDATA_API = "https://pokedata.ovh/events/apiv2/"
POKEDATA_TCG_QUERY = "_tcg/cups/challenges/pre"
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


def _parse_datetime(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _game(raw: dict[str, Any]) -> Game:
    product = (_text(raw.get("Products")) or "").lower()
    event_type = (_text(raw.get("type")) or "").lower()
    if product == "tcg" or "tcg" in event_type:
        return Game.TCG
    if product in {"vg", "vgc", "video game"} or "vg" in event_type:
        return Game.VGC
    if product in {"go", "pokemon go"} or "go" in event_type:
        return Game.GO
    return Game.OTHER


def _status(raw: dict[str, Any]) -> EventStatus:
    value = (_text(raw.get("Status")) or _text(raw.get("status")) or "").lower()
    if any(word in value for word in ("cancel", "deleted", "removed")):
        return EventStatus.CANCELLED
    return EventStatus.ACTIVE


def parse_pokedata_event(raw: dict[str, Any]) -> EventSnapshot:
    """Normalise one sanctioned Play! Pokemon event mirrored by Pokedata.

    Pokedata exposes the Play! Pokemon event GUID, tournament display ID,
    League ID and official pokemon.com URL. The GUID is used as the upstream
    event key because it also covers events without a tournament display ID.
    """

    guid = _text(raw.get("guid")) or _text(raw.get("Guid"))
    if not guid:
        raise EventSourceError("Pokedata event is missing guid/Guid")

    starts_at = _parse_datetime(raw.get("Start_date"))
    if starts_at is None:
        raise EventSourceError(
            f"Pokedata event {guid} has no timezone-aware Start_date"
        )
    if starts_at.tzinfo is None:
        raise EventSourceError(
            f"Pokedata event {guid} returned a naive Start_date"
        )

    event_type = _text(raw.get("type")) or _text(raw.get("Subtype"))
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
    """Resilient mirror/fallback for sanctioned Play! Pokemon event data.

    Play! Pokemon remains the authoritative publisher. This adapter exists so
    PokEvent can consume the mirrored structured records without scraping the
    rendered Event Locator, and every event retains its official pokemon.com
    source URL.
    """

    name = "pokedata"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        delay_seconds: float = 0.25,
        attempts: int = 4,
    ) -> None:
        self._client = client
        self.delay_seconds = delay_seconds
        self.attempts = attempts

    @staticmethod
    def page_url(page: int) -> str:
        return f"{POKEDATA_API}{POKEDATA_TCG_QUERY}/_page/{page}"

    async def _fetch_page(
        self,
        page: int,
        client: httpx.AsyncClient,
    ) -> tuple[list[dict[str, Any]], int, int]:
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                response = await client.get(
                    self.page_url(page),
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
                    },
                )
                response.raise_for_status()
                body = response.json()
                metadata = body.get("metadata")
                events = body.get("events")
                if not isinstance(metadata, dict) or not isinstance(events, list):
                    raise EventSourceError(
                        f"Pokedata page {page} returned an unexpected shape"
                    )

                total_items = metadata.get("total_items")
                total_pages = metadata.get("total_pages")
                current_page = metadata.get("current_page", page)
                if not all(
                    isinstance(value, int) and value >= 0
                    for value in (total_items, total_pages, current_page)
                ):
                    raise EventSourceError(
                        f"Pokedata page {page} returned invalid metadata"
                    )
                if current_page != page:
                    raise EventSourceError(
                        f"Pokedata returned page {current_page} when {page} was requested"
                    )

                dict_events = [event for event in events if isinstance(event, dict)]
                return dict_events, total_items, total_pages
            except (httpx.HTTPError, ValueError, EventSourceError) as exc:
                last_error = exc
                if attempt < self.attempts:
                    await asyncio.sleep(2 ** (attempt - 1))

        raise EventSourceError(
            f"Pokedata page {page} failed after {self.attempts} attempts: {last_error}"
        )

    async def _fetch_all_raw(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        first, total_items, total_pages = await self._fetch_page(1, client)
        events = list(first)

        for page in range(2, total_pages + 1):
            await asyncio.sleep(self.delay_seconds)
            next_events, next_total, next_pages = await self._fetch_page(page, client)
            if next_pages != total_pages:
                raise EventSourceError(
                    "Pokedata page count changed while the catalogue was being fetched"
                )
            if next_total != total_items:
                raise EventSourceError(
                    "Pokedata event count changed while the catalogue was being fetched"
                )
            events.extend(next_events)

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

    async def fetch_events(self, search: EventSearch) -> list[EventSnapshot]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            raw_events = await self._fetch_all_raw(client)
        finally:
            if owns_client:
                await client.aclose()

        results: list[EventSnapshot] = []
        for raw in raw_events:
            try:
                event = parse_pokedata_event(raw)
            except EventSourceError:
                continue

            if search.starts_after and event.starts_at < search.starts_after:
                continue

            if event.latitude is None or event.longitude is None:
                continue

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

            results.append(event)

        return sorted(results, key=lambda event: event.starts_at)

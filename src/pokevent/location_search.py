from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from .config import Settings
from .domain import EventSearch, EventSnapshot
from .sources.pokedata import PokedataSource

POSTCODES_IO = "https://api.postcodes.io"
FULL_POSTCODE_RE = re.compile(
    r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$",
    re.IGNORECASE,
)
OUTCODE_RE = re.compile(
    r"^[A-Z]{1,2}\d[A-Z\d]?$",
    re.IGNORECASE,
)


class LocationSearchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedLocation:
    label: str
    latitude: float
    longitude: float
    kind: str


def _coordinates(result: object) -> tuple[float, float] | None:
    if not isinstance(result, dict):
        return None
    latitude = result.get("latitude")
    longitude = result.get("longitude")
    if not isinstance(latitude, (int, float)) or not isinstance(
        longitude,
        (int, float),
    ):
        return None
    return float(latitude), float(longitude)


async def _json_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str | int] | None = None,
) -> object:
    try:
        response = await client.get(url, params=params)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LocationSearchError("Location lookup is temporarily unavailable.") from exc

    if not isinstance(body, dict):
        raise LocationSearchError("Location lookup returned an unexpected response.")
    return body.get("result")


async def resolve_location(
    query: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> ResolvedLocation:
    cleaned = " ".join(query.strip().split())
    if len(cleaned) < 2:
        raise LocationSearchError("Enter a town or UK postcode.")

    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=10,
        headers={"User-Agent": "PokEvent/3.0 location search"},
    )

    try:
        compact = cleaned.replace(" ", "").upper()

        if FULL_POSTCODE_RE.fullmatch(cleaned):
            result = await _json_get(
                http,
                f"{POSTCODES_IO}/postcodes/{quote(compact, safe='')}",
            )
            coordinates = _coordinates(result)
            if coordinates is None or not isinstance(result, dict):
                raise LocationSearchError("That postcode could not be resolved.")
            return ResolvedLocation(
                label=str(result.get("postcode") or cleaned),
                latitude=coordinates[0],
                longitude=coordinates[1],
                kind="postcode",
            )

        if OUTCODE_RE.fullmatch(cleaned):
            result = await _json_get(
                http,
                f"{POSTCODES_IO}/outcodes/{quote(compact, safe='')}",
            )
            coordinates = _coordinates(result)
            if coordinates is None or not isinstance(result, dict):
                raise LocationSearchError("That postcode district could not be resolved.")
            return ResolvedLocation(
                label=str(result.get("outcode") or cleaned).upper(),
                latitude=coordinates[0],
                longitude=coordinates[1],
                kind="outcode",
            )

        result = await _json_get(
            http,
            f"{POSTCODES_IO}/places",
            params={"q": cleaned, "limit": 10},
        )
        if not isinstance(result, list):
            raise LocationSearchError("That town or place could not be resolved.")

        candidates = [
            row
            for row in result
            if isinstance(row, dict) and _coordinates(row) is not None
        ]
        if not candidates:
            raise LocationSearchError("That town or place could not be resolved.")

        exact = next(
            (
                row
                for row in candidates
                if str(row.get("name_1") or "").casefold() == cleaned.casefold()
            ),
            None,
        )
        chosen = exact or candidates[0]
        coordinates = _coordinates(chosen)
        assert coordinates is not None

        name = str(chosen.get("name_1") or cleaned)
        area = chosen.get("county_unitary") or chosen.get("region")
        label = f"{name}, {area}" if area and area != name else name

        return ResolvedLocation(
            label=label,
            latitude=coordinates[0],
            longitude=coordinates[1],
            kind="place",
        )
    finally:
        if owns_client:
            await http.aclose()


async def search_live_events(
    query: str,
    *,
    radius_miles: int,
    settings: Settings,
) -> tuple[ResolvedLocation, list[EventSnapshot]]:
    location = await resolve_location(query)
    source = PokedataSource(
        country_code=settings.country_code,
        local_timezone=settings.local_timezone,
        horizon_days=settings.event_horizon_days,
        monitored_league_ids=set(),
    )
    search = EventSearch(
        latitude=location.latitude,
        longitude=location.longitude,
        radius_miles=float(radius_miles),
        starts_after=datetime.now(UTC),
    )
    events = await source.fetch_events(search)
    return location, events

from datetime import UTC, datetime

import httpx
import pytest

from pokevent.domain import EventSearch, Game
from pokevent.sources.pokedata import PokedataSource, parse_pokedata_event


def regional_row(
    *,
    guid: str,
    league: str = "2012924",
    event_type: str = "League Challenge",
    when: str = "2026-09-20 11:00:00",
) -> dict:
    return {
        "guid": guid,
        "league": league,
        "type": event_type,
        "name": f"Pokemon League Swindon - {event_type}",
        "shop": "THE INCREDIBLE COMIC SHOP",
        "when": when,
        "date": when[:10],
        "latitude": "51.5606",
        "longitude": "-1.78633",
        "city": "Swindon",
        "country_code": "GB",
        "pokemon_url": "https://www.pokemon.com/play-pokemon-tournaments/example/",
    }


def friendly_row(
    *,
    guid: str,
    type_name: str,
    when: str = "2026-09-21 18:00:00",
) -> dict:
    return {
        "guid": guid,
        "league": "2012924",
        "type": type_name,
        "name": "",
        "shop": "THE INCREDIBLE COMIC SHOP",
        "when": when,
        "date": when[:10],
        "latitude": "51.5606",
        "longitude": "-1.78633",
        "city": "Swindon",
        "country_code": "GB",
        "pokemon_url": "https://www.pokemon.com/play-pokemon-tournaments//",
    }


def test_regional_wall_time_uses_configured_timezone() -> None:
    event = parse_pokedata_event(
        regional_row(guid="challenge"),
        game_hint=Game.TCG,
        local_timezone="Europe/London",
    )

    assert event.game is Game.TCG
    assert event.starts_at.hour == 11
    assert event.starts_at.utcoffset() is not None
    assert event.starts_at.utcoffset().total_seconds() == 3600


def test_unnamed_friendly_when_is_treated_as_utc() -> None:
    event = parse_pokedata_event(
        friendly_row(guid="friendly", type_name="nonpremier TCG"),
        local_timezone="Europe/London",
        table_friendly=True,
    )

    assert event.game is Game.TCG
    assert event.event_type == "League / Friendly"
    assert event.starts_at.utcoffset() is not None
    assert event.starts_at.utcoffset().total_seconds() == 0


@pytest.mark.asyncio
async def test_full_source_combines_tcg_vgc_go_and_friendlies() -> None:
    responses = {
        "_tcg": [regional_row(guid="tcg")],
        "_vg": [regional_row(guid="vg", event_type="League Cup")],
        "_go": [regional_row(guid="go", event_type="League Cup")],
    }
    table_rows = [
        friendly_row(guid="ftcg", type_name="nonpremier TCG"),
        friendly_row(guid="fvg", type_name="nonpremier VG"),
        friendly_row(guid="fgo", type_name="nonpremier GO"),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=table_rows)
        url = str(request.url)
        for marker, payload in responses.items():
            if marker in url:
                return httpx.Response(200, json=payload)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = PokedataSource(
            client=client,
            country_code="GB",
            local_timezone="Europe/London",
        )
        events = await source.fetch_events(
            EventSearch(
                latitude=51.5615,
                longitude=-1.7855,
                radius_miles=30,
                starts_after=datetime(2026, 9, 18, tzinfo=UTC),
            )
        )

    assert {event.upstream_event_id for event in events} == {
        "tcg",
        "vg",
        "go",
        "ftcg",
        "fvg",
        "fgo",
    }
    assert {event.game for event in events} == {Game.TCG, Game.VGC, Game.GO}


@pytest.mark.asyncio
async def test_countrywide_friendly_outside_radius_is_removed() -> None:
    far = friendly_row(guid="far", type_name="nonpremier TCG")
    far["latitude"] = "53.4808"
    far["longitude"] = "-2.2426"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=[far])
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = PokedataSource(client=client)
        events = await source.fetch_events(
            EventSearch(
                latitude=51.5615,
                longitude=-1.7855,
                radius_miles=30,
                starts_after=datetime(2026, 9, 18, tzinfo=UTC),
            )
        )

    assert events == []

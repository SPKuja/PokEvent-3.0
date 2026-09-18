from datetime import UTC, datetime

import httpx
import pytest

from pokevent.domain import EventSearch, Game
from pokevent.routing import RouteCriteria, matches_route
from pokevent.sources.pokedata import PokedataSource, parse_pokedata_event


SWINDON_SHAPE_FIXTURE = {
    "type": "League Challenge",
    "name": "Pokemon League Swindon League Challenge - shape fixture",
    "date": "2026-09-20",
    "shop": "POKEMON LEAGUE SWINDON",
    "street_address": "Fixture address, Swindon, GB",
    "city": "Swindon",
    "country_code": "GB",
    "pokemon_url": (
        "https://www.pokemon.com/us/pokemon-trainer-club/"
        "play-pokemon-tournaments/26-09-FIXTURE/"
    ),
    "guid": "fixture-2012924-2026-09-20",
    "latitude": "51.5615",
    "longitude": "-1.7855",
    "when": "2026-09-20 11:00:00",
    "league": "2012924",
    "Display_id": "26-09-FIXTURE",
    "Products": "tcg",
    "Start_date": "2026-09-20T10:00:00Z",
    "Status": "sanctioned",
    "Admission": "",
}


def test_known_swindon_league_id_maps_to_routing_identity() -> None:
    event = parse_pokedata_event(SWINDON_SHAPE_FIXTURE)

    assert event.upstream_organisation_id == "2012924"
    assert event.game is Game.TCG
    assert event.event_type == "League Challenge"
    assert event.starts_at == datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    assert matches_route(
        event,
        RouteCriteria(upstream_organisation_id="2012924"),
    )


@pytest.mark.asyncio
async def test_source_pages_then_filters_locally() -> None:
    page_1 = {
        "metadata": {
            "total_items": 2,
            "total_pages": 2,
            "current_page": 1,
            "limit": 1,
        },
        "events": [SWINDON_SHAPE_FIXTURE],
    }
    far_event = {
        **SWINDON_SHAPE_FIXTURE,
        "guid": "fixture-far-away",
        "league": "9999999",
        "latitude": "55.9533",
        "longitude": "-3.1883",
    }
    page_2 = {
        "metadata": {
            "total_items": 2,
            "total_pages": 2,
            "current_page": 2,
            "limit": 1,
        },
        "events": [far_event],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        page = int(str(request.url).rsplit("/", 1)[-1])
        return httpx.Response(200, json=page_1 if page == 1 else page_2)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        source = PokedataSource(client=client, delay_seconds=0)
        events = await source.fetch_events(
            EventSearch(
                latitude=51.5615,
                longitude=-1.7855,
                radius_miles=30,
                starts_after=datetime(2026, 9, 18, tzinfo=UTC),
            )
        )

    assert [event.upstream_organisation_id for event in events] == ["2012924"]

from datetime import UTC, datetime

import httpx
import pytest

from pokevent.domain import EventSearch, Game
from pokevent.sources.pokedata import PokedataSource, parse_pokedata_event


def row(
    *,
    guid: str,
    league: str,
    event_type: str,
    product: str,
    latitude: str = "51.5606",
    longitude: str = "-1.78633",
    name: str | None = None,
) -> dict:
    return {
        "guid": guid,
        "league": league,
        "type": event_type,
        "product": product,
        "name": name,
        "shop": "THE INCREDIBLE COMIC SHOP",
        "when": "2026-09-20 11:00:00",
        "date": "2026-09-20",
        "latitude": latitude,
        "longitude": longitude,
        "city": "Swindon",
        "country_code": "GB",
        "pokemon_url": "https://www.pokemon.com/play-pokemon-tournaments/example/",
    }


def test_parser_classifies_all_three_games() -> None:
    tcg = parse_pokedata_event(
        row(
            guid="tcg",
            league="2012924",
            event_type="nonpremier TCG",
            product="tcg",
        )
    )
    vgc = parse_pokedata_event(
        row(
            guid="vgc",
            league="2",
            event_type="nonpremier VG",
            product="vg",
        )
    )
    go = parse_pokedata_event(
        row(
            guid="go",
            league="3",
            event_type="nonpremier GO",
            product="pgo",
        )
    )

    assert tcg.game is Game.TCG
    assert vgc.game is Game.VGC
    assert go.game is Game.GO
    assert tcg.event_type == "League Session"
    assert vgc.event_type == "League / Friendly"
    assert go.event_type == "League / Friendly"


def test_unknown_event_type_is_preserved() -> None:
    event = parse_pokedata_event(
        row(
            guid="future",
            league="2012924",
            event_type="Future Pokemon Event Type",
            product="new-product",
        )
    )

    assert event.game is Game.OTHER
    assert event.event_type == "Future Pokemon Event Type"


@pytest.mark.asyncio
async def test_source_pages_complete_country_date_catalogue_and_filters_locally() -> None:
    page_1 = {
        "metadata": {
            "total_items": 3,
            "total_pages": 2,
            "current_page": 1,
            "limit": 100,
        },
        "events": [
            row(
                guid="swindon",
                league="2012924",
                event_type="League Challenge",
                product="tcg",
            ),
            row(
                guid="nearby-vgc",
                league="other",
                event_type="nonpremier VG",
                product="vg",
                latitude="51.65",
                longitude="-1.90",
            ),
        ],
    }
    page_2 = {
        "metadata": {
            "total_items": 3,
            "total_pages": 2,
            "current_page": 2,
            "limit": 100,
        },
        "events": [
            row(
                guid="far",
                league="far-league",
                event_type="nonpremier GO",
                product="pgo",
                latitude="53.4808",
                longitude="-2.2426",
            ),
        ],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        page = 2 if "/_page/2" in url else 1
        assert "/_country/GB/" in url
        assert "/_start/2026-09-18/" in url
        assert "/_end/2026-12-17/" in url
        return httpx.Response(200, json=page_2 if page == 2 else page_1)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = PokedataSource(
            client=client,
            delay_seconds=0,
            horizon_days=90,
            monitored_league_ids={"2012924"},
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
        "swindon",
        "nearby-vgc",
    }


@pytest.mark.asyncio
async def test_monitored_league_survives_distance_filter() -> None:
    payload = {
        "metadata": {
            "total_items": 1,
            "total_pages": 1,
            "current_page": 1,
            "limit": 100,
        },
        "events": [
            row(
                guid="away-day",
                league="2012924",
                event_type="League Cup",
                product="tcg",
                latitude="52.4862",
                longitude="-1.8904",
            )
        ],
    }

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = PokedataSource(
            client=client,
            delay_seconds=0,
            monitored_league_ids={"2012924"},
        )
        events = await source.fetch_events(
            EventSearch(
                latitude=51.5615,
                longitude=-1.7855,
                radius_miles=30,
                starts_after=datetime(2026, 9, 18, tzinfo=UTC),
            )
        )

    assert [event.upstream_event_id for event in events] == ["away-day"]


@pytest.mark.asyncio
async def test_source_rejects_repeated_or_wrong_page() -> None:
    payload = {
        "metadata": {
            "total_items": 101,
            "total_pages": 2,
            "current_page": 1,
            "limit": 100,
        },
        "events": [
            row(
                guid="one",
                league="2012924",
                event_type="League Challenge",
                product="tcg",
            )
        ],
    }

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = PokedataSource(client=client, attempts=1, delay_seconds=0)
        with pytest.raises(Exception, match="returned page 1 when 2 was requested"):
            await source.fetch_events(
                EventSearch(
                    latitude=51.5615,
                    longitude=-1.7855,
                    radius_miles=30,
                    starts_after=datetime(2026, 9, 18, tzinfo=UTC),
                )
            )

from datetime import UTC, datetime

from pokevent.domain import Game
from pokevent.routing import RouteCriteria, matches_route
from pokevent.sources.pokedata import parse_pokedata_event

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
    "product": "tcg",
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

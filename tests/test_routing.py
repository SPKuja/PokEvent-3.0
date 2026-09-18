from datetime import UTC, datetime

from pokevent.domain import EventSnapshot, Game
from pokevent.routing import RouteCriteria, matches_route


def event(**overrides) -> EventSnapshot:
    values = {
        "source": "play_pokemon",
        "upstream_event_id": "evt-1",
        "upstream_organisation_id": "atomic-cards",
        "upstream_location_id": "atomic-swindon",
        "title": "League Challenge",
        "game": Game.TCG,
        "starts_at": datetime(2026, 10, 10, 10, 0, tzinfo=UTC),
        "latitude": 51.56,
        "longitude": -1.78,
    }
    values.update(overrides)
    return EventSnapshot(**values)


def test_routes_by_organisation() -> None:
    route = RouteCriteria(upstream_organisation_id="atomic-cards")
    assert matches_route(event(), route)


def test_rejects_different_organisation() -> None:
    route = RouteCriteria(upstream_organisation_id="another-league")
    assert not matches_route(event(), route)


def test_routes_by_game() -> None:
    assert matches_route(event(), RouteCriteria(game=Game.TCG))
    assert not matches_route(event(), RouteCriteria(game=Game.VGC))


def test_routes_by_distance() -> None:
    nearby = RouteCriteria(
        centre_latitude=51.5615,
        centre_longitude=-1.7855,
        max_distance_miles=5,
    )
    assert matches_route(event(), nearby)


def test_distance_route_requires_event_coordinates() -> None:
    route = RouteCriteria(
        centre_latitude=51.5615,
        centre_longitude=-1.7855,
        max_distance_miles=30,
    )
    assert not matches_route(event(latitude=None, longitude=None), route)

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from .domain import EventSnapshot, Game


@dataclass(frozen=True, slots=True)
class RouteCriteria:
    upstream_organisation_id: str | None = None
    upstream_location_id: str | None = None
    game: Game | None = None
    centre_latitude: float | None = None
    centre_longitude: float | None = None
    max_distance_miles: float | None = None


def distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_miles = 3958.7613
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return 2 * earth_radius_miles * asin(sqrt(a))


def matches_route(event: EventSnapshot, route: RouteCriteria) -> bool:
    if (
        route.upstream_organisation_id is not None
        and event.upstream_organisation_id != route.upstream_organisation_id
    ):
        return False

    if (
        route.upstream_location_id is not None
        and event.upstream_location_id != route.upstream_location_id
    ):
        return False

    if route.game is not None and event.game != route.game:
        return False

    if route.max_distance_miles is not None:
        coordinates = (
            route.centre_latitude,
            route.centre_longitude,
            event.latitude,
            event.longitude,
        )
        if any(value is None for value in coordinates):
            return False

        assert route.centre_latitude is not None
        assert route.centre_longitude is not None
        assert event.latitude is not None
        assert event.longitude is not None

        distance = distance_miles(
            route.centre_latitude,
            route.centre_longitude,
            event.latitude,
            event.longitude,
        )
        if distance > route.max_distance_miles:
            return False

    return True

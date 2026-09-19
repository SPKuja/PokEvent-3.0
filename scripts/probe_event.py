from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime

from pokevent.domain import EventSearch
from pokevent.sources.pokedata import PokedataSource


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe the structured Play! Pokemon mirror for one League/date."
    )
    parser.add_argument("--league", required=True)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--lat", required=True, type=float)
    parser.add_argument("--lon", required=True, type=float)
    parser.add_argument("--radius", type=float, default=50)
    return parser.parse_args()


async def run() -> int:
    args = arguments()
    source = PokedataSource()
    start = datetime.combine(args.date, datetime.min.time(), tzinfo=UTC)

    events = await source.fetch_events(
        EventSearch(
            latitude=args.lat,
            longitude=args.lon,
            radius_miles=args.radius,
            starts_after=start,
        )
    )

    matches = [
        event
        for event in events
        if event.upstream_organisation_id == args.league
        and event.starts_at.date() == args.date
    ]

    print(
        json.dumps(
            [
                {
                    "source": event.source,
                    "upstream_event_id": event.upstream_event_id,
                    "league_id": event.upstream_organisation_id,
                    "title": event.title,
                    "game": event.game.value if event.game else None,
                    "event_type": event.event_type,
                    "starts_at": event.starts_at.isoformat(),
                    "venue_name": event.venue_name,
                    "address": event.address,
                    "city": event.city,
                    "pokemon_url": event.source_url,
                    "display_id": (
                        event.upstream_payload or {}
                    ).get("Display_id"),
                }
                for event in matches
            ],
            indent=2,
            sort_keys=True,
        )
    )

    if not matches:
        print(
            f"No event found for league={args.league} date={args.date.isoformat()} "
            f"inside {args.radius:g} miles."
        )
        return 1

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()

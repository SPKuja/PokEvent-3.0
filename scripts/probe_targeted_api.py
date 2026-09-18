from __future__ import annotations

import asyncio
import json

import httpx

URL = (
    "https://www.pokedata.ovh/events/api/_tcg/challenges"
    "/_latitude/51.5615/_longitude/-1.7855"
    "/_radius/50/_unit/mi/_start/2026-09-18"
)
LEAGUE_ID = "2012924"
DATE = "2026-09-20"

SAFE_FIELDS = (
    "guid",
    "Guid",
    "Display_id",
    "league",
    "type",
    "name",
    "Name",
    "shop",
    "date",
    "when",
    "Start_date",
    "Products",
    "Status",
    "latitude",
    "longitude",
    "street_address",
    "city",
    "country_code",
    "pokemon_url",
)


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(
            URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
            },
        )
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected targeted API shape: {type(payload).__name__}")

    matches = [
        row
        for row in payload
        if isinstance(row, dict)
        and str(row.get("league", "")).strip() == LEAGUE_ID
        and str(row.get("date", "")).strip() == DATE
    ]

    print(f"targeted endpoint returned {len(payload)} challenge records")
    print(f"matches for league={LEAGUE_ID} date={DATE}: {len(matches)}")
    print(
        json.dumps(
            [
                {field: row.get(field) for field in SAFE_FIELDS if field in row}
                for row in matches
            ],
            indent=2,
            sort_keys=True,
        )
    )

    if not matches:
        # Print only coarse non-sensitive identifiers for same-date rows to aid debugging.
        same_date = [
            {
                "league": row.get("league"),
                "shop": row.get("shop"),
                "type": row.get("type"),
                "date": row.get("date"),
                "city": row.get("city"),
                "Display_id": row.get("Display_id"),
            }
            for row in payload
            if isinstance(row, dict) and str(row.get("date", "")).strip() == DATE
        ]
        print("same-date rows:")
        print(json.dumps(same_date, indent=2, sort_keys=True))
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())

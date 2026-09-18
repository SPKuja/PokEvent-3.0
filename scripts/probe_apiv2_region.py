from __future__ import annotations

import asyncio
import json
from collections import Counter

import httpx

BASE = "https://pokedata.ovh/events/apiv2"
QUERY = (
    "_country/GB"
    "/_start/2026-09-18"
    "/_end/2026-11-15"
    "/_latitude/51.5615"
    "/_longitude/-1.7855"
    "/_radius/50"
    "/_unit/miles"
)


async def main() -> None:
    async with httpx.AsyncClient(timeout=45) as client:
        all_events: list[dict] = []
        total_pages = None

        for page in range(1, 6):
            response = await client.get(
                f"{BASE}/{QUERY}/_page/{page}",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
                },
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise RuntimeError(f"page {page}: unexpected {type(body).__name__}")

            meta = body.get("metadata")
            events = body.get("events")
            if not isinstance(meta, dict) or not isinstance(events, list):
                raise RuntimeError(f"page {page}: unexpected response shape")

            print("page", page, "metadata", json.dumps(meta, sort_keys=True))
            if meta.get("current_page") != page:
                raise RuntimeError(
                    f"asked for page {page}, received {meta.get('current_page')}"
                )

            if total_pages is None:
                total_pages = int(meta.get("total_pages", 0))

            all_events.extend(row for row in events if isinstance(row, dict))
            if page >= total_pages:
                break

        print("fetched rows", len(all_events))
        print(
            "types",
            json.dumps(
                dict(Counter(str(row.get("type")) for row in all_events)),
                sort_keys=True,
            ),
        )
        print(
            "products",
            json.dumps(
                dict(
                    Counter(
                        str(row.get("product") or row.get("Products"))
                        for row in all_events
                    )
                ),
                sort_keys=True,
            ),
        )

        swindon = [
            {
                "guid": row.get("guid") or row.get("Guid"),
                "Display_id": row.get("Display_id"),
                "league": row.get("league"),
                "type": row.get("type"),
                "product": row.get("product") or row.get("Products"),
                "name": row.get("name") or row.get("Name"),
                "shop": row.get("shop"),
                "date": row.get("date"),
                "when": row.get("when"),
                "Start_date": row.get("Start_date"),
                "city": row.get("city"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "pokemon_url": row.get("pokemon_url"),
            }
            for row in all_events
            if str(row.get("league", "")).strip() == "2012924"
        ]
        print("league 2012924", json.dumps(swindon, indent=2, sort_keys=True))

        known = [
            row
            for row in all_events
            if str(row.get("league", "")).strip() == "2012924"
            and str(row.get("date", "")).strip() == "2026-09-20"
        ]
        if not known:
            raise SystemExit("known Swindon event missing from generic apiv2 query")


if __name__ == "__main__":
    asyncio.run(main())

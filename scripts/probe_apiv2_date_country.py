from __future__ import annotations

import asyncio
import json
from collections import Counter

import httpx

BASE = "https://pokedata.ovh/events/apiv2"
QUERIES = {
    "country_dates": "_country/GB/_start/2026-09-18/_end/2026-11-15",
    "dates_only": "_start/2026-09-18/_end/2026-11-15",
    "country_only": "_country/GB",
}


async def probe(client: httpx.AsyncClient, label: str, query: str) -> None:
    response = await client.get(
        f"{BASE}/{query}/_page/1",
        headers={
            "Accept": "application/json",
            "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
        },
    )
    response.raise_for_status()
    body = response.json()
    meta = body.get("metadata") if isinstance(body, dict) else None
    events = body.get("events") if isinstance(body, dict) else None
    print("===", label, "===")
    print("metadata", json.dumps(meta, sort_keys=True))
    if not isinstance(events, list):
        print("invalid events shape")
        return
    print(
        "types",
        json.dumps(
            dict(Counter(str(row.get("type")) for row in events if isinstance(row, dict))),
            sort_keys=True,
        ),
    )
    print(
        "countries",
        sorted(
            {
                str(row.get("country_code"))
                for row in events
                if isinstance(row, dict)
            }
        )[:20],
    )
    known = [
        {
            "guid": row.get("guid") or row.get("Guid"),
            "league": row.get("league"),
            "type": row.get("type"),
            "product": row.get("product") or row.get("Products"),
            "name": row.get("name") or row.get("Name"),
            "date": row.get("date"),
            "when": row.get("when"),
            "city": row.get("city"),
        }
        for row in events
        if isinstance(row, dict)
        and str(row.get("league", "")).strip() == "2012924"
    ]
    print("league2012924 first-page", json.dumps(known, indent=2, sort_keys=True))


async def main() -> None:
    async with httpx.AsyncClient(timeout=45) as client:
        for label, query in QUERIES.items():
            await probe(client, label, query)


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import asyncio
import json
from collections import Counter

import httpx

URL = "https://www.pokedata.ovh/events/tableapi/index_table.php"
LEAGUE_ID = "2012924"
PAGE_SIZE = 100

QUERY = {
    "past": "",
    "country": "",
    "city": "",
    "shop": "",
    "league": LEAGUE_ID,
    "states": "[]",
    "postcode": "",
    "cups": "1",
    "challenges": "1",
    "vcups": "1",
    "vchallenges": "1",
    "prereleases": "1",
    "premier": "1",
    "go": "1",
    "gocup": "1",
    "mss": "1",
    "ftcg": "1",
    "fvg": "1",
    "fgo": "1",
    "latitude": "",
    "longitude": "",
    "radius": "",
    "unit": "mi",
    "width": 1400,
}


async def main() -> None:
    rows: list[dict] = []

    async with httpx.AsyncClient(timeout=60) as client:
        for page in range(10):
            response = await client.post(
                URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
                },
                json={**QUERY, "page": page},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError(
                    f"unexpected response shape on page {page}: "
                    f"{type(payload).__name__}"
                )

            page_rows = [row for row in payload if isinstance(row, dict)]
            rows.extend(page_rows)
            if len(page_rows) < PAGE_SIZE:
                break

    wrong_league = [
        row for row in rows if str(row.get("league", "")).strip() != LEAGUE_ID
    ]
    if wrong_league:
        raise RuntimeError(
            f"league filter leaked {len(wrong_league)} rows for other leagues"
        )

    types = Counter(str(row.get("type", "")).strip() for row in rows)
    print(f"league-only query returned {len(rows)} rows")
    print("types:", json.dumps(dict(types), sort_keys=True))

    safe = []
    for row in rows:
        safe.append(
            {
                "league": row.get("league"),
                "type": row.get("type"),
                "name": row.get("name") or row.get("Name"),
                "shop": row.get("shop"),
                "date": row.get("date"),
                "when": row.get("when"),
                "guid": row.get("guid") or row.get("Guid"),
                "Display_id": row.get("Display_id"),
                "Products": row.get("Products"),
                "city": row.get("city"),
                "pokemon_url": row.get("pokemon_url"),
            }
        )

    print(json.dumps(safe[:20], indent=2, sort_keys=True))

    known = [
        row
        for row in rows
        if str(row.get("date", "")).strip() == "2026-09-20"
        and str(row.get("type", "")).strip() == "League Challenge"
    ]
    print(f"known 2026-09-20 League Challenge matches: {len(known)}")
    if not known:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())

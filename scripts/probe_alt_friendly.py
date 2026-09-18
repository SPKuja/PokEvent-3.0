from __future__ import annotations

import asyncio
import json

import httpx

URL = "https://pokedata.ovh/events/tableapi/"

BASE = {
    "past": "",
    "country": "GB",
    "city": "",
    "shop": "",
    "league": "",
    "states": "[]",
    "postcode": "",
    "cups": "",
    "challenges": "",
    "vcups": "",
    "vchallenges": "",
    "prereleases": "",
    "premier": "",
    "go": "",
    "gocup": "",
    "mss": "",
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
    async with httpx.AsyncClient(timeout=60) as client:
        pages = []
        for page in (0, 1):
            response = await client.post(
                URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json; charset=UTF-8",
                    "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
                },
                json={**BASE, "page": page},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError(
                    f"page {page}: unexpected {type(payload).__name__}"
                )
            pages.append(payload)
            print(f"page {page}: {len(payload)} rows")

    ids = [
        {
            str(row.get("guid") or row.get("Guid"))
            for row in page
            if isinstance(row, dict) and (row.get("guid") or row.get("Guid"))
        }
        for page in pages
    ]
    print("page0 ids", len(ids[0]))
    print("page1 ids", len(ids[1]))
    print("overlap", len(ids[0] & ids[1]))
    print("identical", ids[0] == ids[1])

    league_rows = [
        {
            "guid": row.get("guid"),
            "league": row.get("league"),
            "type": row.get("type"),
            "name": row.get("name"),
            "shop": row.get("shop"),
            "date": row.get("date"),
            "when": row.get("when"),
            "city": row.get("city"),
        }
        for page in pages
        for row in page
        if isinstance(row, dict)
        and str(row.get("league", "")).strip() == "2012924"
    ]
    print("league 2012924", json.dumps(league_rows, indent=2, sort_keys=True))

    if len(pages[0]) == 100 and ids[0] == ids[1]:
        raise SystemExit("pagination is repeating page 0")


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import asyncio
import json
from collections import Counter

import httpx

BASE = "https://pokedata.ovh/events/api"
LAT = "51.5615"
LON = "-1.7855"
RADIUS = "50"
START = "2026-09-18"
LEAGUE = "2012924"

REGIONAL = {
    "tcg": f"{BASE}/_tcg/cups/challenges/pre/_latitude/{LAT}/_longitude/{LON}/_radius/{RADIUS}/_unit/mi/_start/{START}",
    "vgc": f"{BASE}/_vg/cups/challenges/_latitude/{LAT}/_longitude/{LON}/_radius/{RADIUS}/_unit/mi/_start/{START}",
    "go": f"{BASE}/_go/cups/challenges/_latitude/{LAT}/_longitude/{LON}/_radius/{RADIUS}/_unit/mi/_start/{START}",
}
TABLE = "https://www.pokedata.ovh/events/tableapi/index_table.php"

FRIENDLY_QUERY = {
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


def safe(row: dict) -> dict:
    fields = (
        "guid", "Guid", "Display_id", "league", "type", "name", "Name",
        "shop", "date", "when", "Start_date", "Products", "product",
        "city", "country_code", "latitude", "longitude", "pokemon_url",
    )
    return {field: row.get(field) for field in fields if field in row}


async def main() -> None:
    headers = {
        "Accept": "application/json",
        "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        for label, url in REGIONAL.items():
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError(f"{label}: unexpected {type(payload).__name__}")
            print(f"=== {label.upper()} regional: {len(payload)} ===")
            print("types", json.dumps(dict(Counter(str(r.get("type")) for r in payload if isinstance(r, dict))), sort_keys=True))
            league_rows = [r for r in payload if isinstance(r, dict) and str(r.get("league","")).strip() == LEAGUE]
            print(f"league {LEAGUE}: {len(league_rows)}")
            print(json.dumps([safe(r) for r in league_rows[:10]], indent=2, sort_keys=True))

        friendly_rows: list[dict] = []
        for page in range(20):
            response = await client.post(
                TABLE,
                headers={**headers, "Content-Type": "application/json"},
                json={**FRIENDLY_QUERY, "page": page},
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                print("friendly endpoint non-json on page", page, response.text[:200])
                break
            if not isinstance(payload, list):
                raise RuntimeError(f"friendlies page {page}: unexpected {type(payload).__name__}")
            rows = [r for r in payload if isinstance(r, dict)]
            friendly_rows.extend(rows)
            if len(rows) < 100:
                break

        print(f"=== GB FRIENDLIES sampled: {len(friendly_rows)} ===")
        print("types", json.dumps(dict(Counter(str(r.get("type")) for r in friendly_rows)), sort_keys=True))
        league_rows = [r for r in friendly_rows if str(r.get("league","")).strip() == LEAGUE]
        print(f"league {LEAGUE}: {len(league_rows)}")
        print(json.dumps([safe(r) for r in league_rows[:20]], indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())

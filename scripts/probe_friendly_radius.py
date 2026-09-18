from __future__ import annotations

import asyncio
import json
from collections import Counter

import httpx

TABLE = "https://www.pokedata.ovh/events/tableapi/index_table.php"

BASE = {
    "past": "",
    "country": "",
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
    "ftcg": "",
    "fvg": "",
    "fgo": "",
    "latitude": "51.5615",
    "longitude": "-1.7855",
    "radius": "50",
    "unit": "mi",
    "width": 1400,
    "page": 0,
}

STREAMS = {
    "ftcg": {"ftcg": "1"},
    "fvg": {"fvg": "1"},
    "fgo": {"fgo": "1"},
    "all": {"ftcg": "1", "fvg": "1", "fgo": "1"},
}


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        for label, flags in STREAMS.items():
            response = await client.post(
                TABLE,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
                },
                json={**BASE, **flags},
            )
            print(f"=== {label} HTTP {response.status_code} ===")
            try:
                payload = response.json()
            except ValueError:
                print(response.text[:500])
                continue
            if not isinstance(payload, list):
                print("unexpected", type(payload).__name__)
                continue
            print("rows", len(payload))
            print("types", json.dumps(dict(Counter(str(r.get("type")) for r in payload if isinstance(r, dict))), sort_keys=True))
            swindon = [
                {
                    "guid": r.get("guid"),
                    "league": r.get("league"),
                    "type": r.get("type"),
                    "name": r.get("name"),
                    "shop": r.get("shop"),
                    "date": r.get("date"),
                    "when": r.get("when"),
                    "city": r.get("city"),
                    "product": r.get("product"),
                    "distance": r.get("distance"),
                }
                for r in payload
                if isinstance(r, dict)
                and str(r.get("league", "")).strip() == "2012924"
            ]
            print("league 2012924", json.dumps(swindon[:10], indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import asyncio
import json
from collections import Counter

import httpx

URLS = [
    "https://pokedata.ovh/events/tableapi/",
    "https://www.pokedata.ovh/events/tableapi/",
]

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
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for url in URLS:
            response = await client.post(
                url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json; charset=UTF-8",
                    "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
                },
                json=BASE,
            )
            print("URL", url, "HTTP", response.status_code, "final", response.url)
            try:
                payload = response.json()
            except ValueError:
                print(response.text[:700])
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
                }
                for r in payload
                if isinstance(r, dict)
                and str(r.get("league", "")).strip() == "2012924"
            ]
            print("league 2012924", json.dumps(swindon[:20], indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())

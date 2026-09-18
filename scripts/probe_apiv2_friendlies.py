from __future__ import annotations

import asyncio
import json

import httpx

BASE = "https://pokedata.ovh/events/apiv2"
CANDIDATES = [
    "_tcg/friendly/_page/1",
    "_tcg/nonpremier/_page/1",
    "_tcg/locals/_page/1",
    "_tcg/cups/challenges/pre/friendly/_page/1",
    "_tcg/cups/challenges/pre/nonpremier/_page/1",
    "_tcg/cups/challenges/pre/locals/_page/1",
]


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        for suffix in CANDIDATES:
            url = f"{BASE}/{suffix}"
            try:
                response = await client.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
                    },
                )
                print("URL", suffix, "HTTP", response.status_code)
                try:
                    body = response.json()
                except ValueError:
                    print(response.text[:300].replace("\n", " "))
                    continue

                if isinstance(body, dict):
                    meta = body.get("metadata")
                    events = body.get("events")
                    print("metadata", json.dumps(meta, sort_keys=True))
                    if isinstance(events, list):
                        types = sorted(
                            {
                                str(row.get("type"))
                                for row in events
                                if isinstance(row, dict)
                            }
                        )
                        print("events", len(events), "types", types)
                    else:
                        print("keys", sorted(body.keys()))
                elif isinstance(body, list):
                    print("list", len(body))
                else:
                    print("shape", type(body).__name__)
            except Exception as exc:
                print("ERROR", suffix, repr(exc))


if __name__ == "__main__":
    asyncio.run(main())

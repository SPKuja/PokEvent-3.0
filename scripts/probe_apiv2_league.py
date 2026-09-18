from __future__ import annotations

import asyncio
import json

import httpx

BASE = "https://pokedata.ovh/events/apiv2"
CANDIDATES = [
    "_league/2012924/_page/1",
    "_tcg/_league/2012924/_page/1",
    "_tcg/league/2012924/_page/1",
    "_tcg/cups/challenges/pre/_league/2012924/_page/1",
    "_tcg/cups/challenges/pre/league/2012924/_page/1",
]


async def main() -> None:
    timeout = httpx.Timeout(12)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for suffix in CANDIDATES:
            try:
                response = await client.get(
                    f"{BASE}/{suffix}",
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
                    },
                )
                print("URL", suffix, "HTTP", response.status_code)
                body = response.json()
                if not isinstance(body, dict):
                    print("shape", type(body).__name__)
                    continue
                meta = body.get("metadata")
                events = body.get("events")
                print("metadata", json.dumps(meta, sort_keys=True))
                if isinstance(events, list):
                    leagues = sorted(
                        {
                            str(row.get("league"))
                            for row in events
                            if isinstance(row, dict)
                        }
                    )
                    types = sorted(
                        {
                            str(row.get("type"))
                            for row in events
                            if isinstance(row, dict)
                        }
                    )
                    print("events", len(events), "leagues", leagues[:10], "types", types)
            except Exception as exc:
                print("ERROR", suffix, type(exc).__name__, str(exc)[:150])


if __name__ == "__main__":
    asyncio.run(main())

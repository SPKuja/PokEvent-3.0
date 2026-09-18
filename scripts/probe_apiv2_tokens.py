from __future__ import annotations

import asyncio
import json

import httpx

BASE = "https://pokedata.ovh/events/apiv2"
CANDIDATES = [
    "_tcg/ftcg/_page/1",
    "_vg/fvg/_page/1",
    "_go/fgo/_page/1",
    "ftcg/_page/1",
    "fvg/_page/1",
    "fgo/_page/1",
    "_ftcg/_page/1",
    "_fvg/_page/1",
    "_fgo/_page/1",
]


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        for suffix in CANDIDATES:
            response = await client.get(
                f"{BASE}/{suffix}",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
                },
            )
            print("URL", suffix, "HTTP", response.status_code)
            try:
                body = response.json()
            except ValueError:
                print(response.text[:200].replace("\n", " "))
                continue
            if not isinstance(body, dict):
                print("shape", type(body).__name__)
                continue

            meta = body.get("metadata")
            events = body.get("events")
            types = sorted(
                {
                    str(row.get("type"))
                    for row in events or []
                    if isinstance(row, dict)
                }
            )
            products = sorted(
                {
                    str(row.get("product") or row.get("Products"))
                    for row in events or []
                    if isinstance(row, dict)
                }
            )
            print("metadata", json.dumps(meta, sort_keys=True))
            print("types", types)
            print("products", products)


if __name__ == "__main__":
    asyncio.run(main())

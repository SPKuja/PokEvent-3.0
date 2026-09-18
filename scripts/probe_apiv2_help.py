from __future__ import annotations

import asyncio

import httpx

URLS = [
    "https://pokedata.ovh/events/apiv2/help",
    "https://pokedata.ovh/events/apiv2/help/",
]


async def main() -> None:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for url in URLS:
            try:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": "PokEvent/3.0 (+https://github.com/SPKuja/PokEvent-3.0)",
                    },
                )
                print("URL", url, "status", response.status_code, "final", response.url)
                print("content-type", response.headers.get("content-type"))
                text = response.text
                print(text[:12000])
                print("---END PREVIEW---")
            except Exception as exc:
                print("ERROR", url, type(exc).__name__, str(exc))


if __name__ == "__main__":
    asyncio.run(main())

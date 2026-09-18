# Event source research

## Known Swindon identity fixture

Pokemon League Swindon's known Play! Pokemon League ID is **2012924**.

A known League Challenge is scheduled for **20 September 2026**. This is used
only as an identity/date/type fixture while developing ingestion. Synthetic
fixture IDs and times in tests are explicitly marked as fixtures and are not
claimed to be the live event's official tournament ID or start time.

## Structured mirror findings

Pokedata's event API mirrors sanctioned Play! Pokemon records and exposes a
useful structured shape including:

- `guid` / `Guid`: event GUID
- `Display_id`: official tournament display ID
- `league`: Play! Pokemon League ID
- `type`: League Cup / League Challenge / Prerelease
- `Products`: TCG/VG/GO product
- `Start_date`, registration timestamps
- venue/address/coordinates
- official `pokemon_url`
- registration/admission fields

The API v2 response is paginated under `metadata` + `events`.

PokEvent uses `league` as the upstream organisation routing identity. For
Pokemon League Swindon that means a Discord route can target `2012924`
without relying on the text "Pokemon League Swindon".

## Source policy

Play! Pokemon remains the authoritative publisher.

The official Event Locator is currently protected in a way that makes direct
server-side inspection unreliable. PokEvent therefore keeps the official
adapter isolated and adds a Pokedata adapter as a structured mirror/fallback.
Every mirrored event retains the official pokemon.com URL and upstream IDs.

Pokedata's own geographic/date query filters have been reported unreliable by
other open-source consumers, so PokEvent fetches validated pages and applies
distance/date filtering locally.

# Event source research

## Known Swindon event

Pokémon League Swindon's Play! Pokémon League ID is **2012924**.

The known League Challenge on **20 September 2026** was verified against the
live structured source:

- League ID: `2012924`
- event GUID: `7a4dd5c6-fe4e-499e-ac99-612319c4d229`
- tournament display ID: `26-09-021255`
- title: `Pokemon League Swindon - September League Challenge`
- venue: `THE INCREDIBLE COMIC SHOP`
- city: Swindon
- listed start: `2026-09-20 11:00:00`

This proves League identity and venue identity must remain separate.

## Source policy

Play! Pokémon remains the authoritative publisher. PokEvent consumes structured
records mirrored by Pokédata because the rendered official Event Locator is
protected against reliable server-side access. Every mirrored record retains
its official Pokémon event URL and Play! Pokémon identifiers.

Pokédata API v2 is the supported integration surface:

`https://pokedata.ovh/events/apiv2/`

The older `tableapi` endpoints are not used by PokEvent. Pokédata has announced
that tableapi is being retired.

## API v2 contract

The API-v2 help page documents:

- pagination with `_page/<n>`;
- TCG event filters with `_tcg/cups/challenges/pre`;
- VG event filters with `_vg/cups/challenges`;
- GO event filters with `_go/cups/challenges`;
- country filtering with `_country/<alpha-2>`;
- `_start/YYYY-MM-DD` and `_end/YYYY-MM-DD`;
- state and city filters;
- latitude/longitude/radius filters;
- ICS output.

Unknown path filters are silently ignored with HTTP 200, so PokEvent validates
pagination metadata and response completeness instead of assuming a successful
HTTP response means a requested filter was honoured.

## Full-coverage strategy

PokEvent deliberately does **not** ask upstream only for Cups, Challenges or
Prereleases.

It queries the complete bounded country/date catalogue:

`_country/GB/_start/<date>/_end/<date>/_page/<n>`

That catalogue contains premier and non-premier records together, including:

- TCG League Cups and Challenges;
- TCG Prereleases;
- VGC League Cups and Challenges;
- Pokémon GO League Cups and Challenges;
- normal/friendly TCG League listings;
- normal/friendly VGC League listings;
- normal/friendly GO League listings;
- any new event types that Pokédata/Play! Pokémon adds later.

Unknown event types are retained rather than discarded.

The documented API-v2 radius filter currently returns empty results for valid
Swindon searches, so PokEvent applies geographic filtering locally.

## League registry

Known communities are configured by stable Play! Pokémon League ID:

```env
POKEVENT_LEAGUES={"2012924":"Pokémon League Swindon"}
```

The ID is the identity. The friendly text is presentation only.

Configured League IDs bypass the local discovery-radius cut. This is
intentional: if Pokémon League Swindon runs an event at a different or distant
venue, it is still an event belonging to League `2012924` and should remain in
that League's feed.

Events belonging to other Leagues are retained when they fall inside the
service-level discovery radius, allowing PokEvent to surface the wider local
community without asking Discord server owners to configure coordinates.

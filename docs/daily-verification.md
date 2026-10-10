# Optional daily independent event verification

PokEvent discovers events via Pokédata API v2. A second independently operated,
**authorised** HTTPS JSON feed can now verify known tournament IDs and provide
corrections once per 24 hours.

**Important:** Pokémon has not published a verified third-party API for this
integration. PokEvent does not attempt to scrape Event Locator / Play! Tools,
bypass anti-bot protections, or use users' Pokémon credentials. Until an
authorised independent source is supplied, this feature stays disabled.

## Configuration

In Portainer stack environment or `.env`:

```env
POKEVENT_VERIFICATION_FEED_URL=https://approved-provider.example/leagues/{league_id}/events
POKEVENT_VERIFICATION_FEED_TOKEN=optional-secret-bearer-token
POKEVENT_VERIFICATION_INTERVAL_HOURS=24
```

The URL must be HTTPS and include `{league_id}`. Do not embed credentials in
the URL. PokEvent checks **only the League IDs configured in
`POKEVENT_LEAGUES`**, which default to the five service leagues.

## Required feed response

Each `GET` for one league returns JSON, with all status values explicit:

```json
{
  "league_id": "2012924",
  "events": [
    {
      "league_id": "2012924",
      "tournament_id": "26-10-007632",
      "status": "cancelled"
    },
    {
      "league_id": "2012924",
      "tournament_id": "26-10-023392",
      "status": "active",
      "title": "Pokemon League Swindon - October League Challenge",
      "starts_at": "2026-10-18T11:00:00+01:00",
      "venue_name": "THE INCREDIBLE COMIC SHOP"
    }
  ]
}
```

`status` must be `active` or `cancelled`. `title`, `starts_at`
(with UTC offset), and `venue_name` are optional; omitted fields retain their
Pokédata values. The `tournament_id` matches Pokémon's public tournament ID,
not Pokédata's internal event GUID.

The verifier validates every league ID and event before saving corrections.
It does not infer cancellation when an event is missing from the feed. Errors
leave previous verification intact, are logged, and will be retried next cycle.

Corrections persist across restarts, are reapplied to each ordinary Pokédata
sync, and use the existing announcement and crossed-out summary behaviour.
Successful verification is checkpointed in PostgreSQL to enforce the daily
cadence even after container restarts.

## Testing

To test without live access, use a self-hosted mock HTTP server with the
contract above and point `POKEVENT_VERIFICATION_FEED_URL` at its authorised HTTPS
endpoint. Never set this URL to an unverified Pokémon API or a URL that requires
bypassing access controls.

Until a lawful official or independent data feed is available, use admin
controls or source fixes for status corrections. The daily verifier cannot
magically detect edits from Pokédata alone.

# PokEvent 3.0

PokEvent 3.0 is a community-first Pokémon event discovery and publishing platform.

Its goal is to keep players informed about sanctioned Play! Pokémon events in and around their local community, while giving Discord server owners fine-grained control over which League or venue events are posted to which channels.

## 3.0 direction

- Play! Pokémon is the primary event source.
- Events are normalised into a local catalogue before being published anywhere.
- Discord is an output, not the source of truth.
- Server owners can route events by League/Activity Group, venue/location, game and distance.
- A public web calendar and subscribable iCalendar feeds expose the same catalogue.
- The ingestion layer is isolated so Pokémon website/API changes do not infect the rest of the application.

## Initial milestone

1. Establish the application, database and configuration foundation.
2. Investigate and implement reliable Play! Pokémon event ingestion.
3. Preserve stable upstream identifiers for events, organisers/Activity Groups and locations.
4. Add Discord guild configuration and event-routing rules.
5. Add event announcements, updates and commands.
6. Add the public calendar and iCalendar feeds.

## Status

Early 3.0 development.

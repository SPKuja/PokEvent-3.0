# PokEvent 3.0 architecture

## Principle

PokEvent stores one normalised event catalogue and treats Discord, the public web
calendar and iCalendar as outputs of that catalogue.

## Flow

```text
Play! Pokémon
      |
      v
Source adapter
      |
      v
Normalised catalogue -----> Web calendar / API / iCalendar
      |
      v
Routing engine
      |
      v
Discord guild + channel announcements
```

## Stable identity

PokEvent owns its own internal identifiers. Upstream Play! Pokémon identifiers
are retained separately:

- event identifier
- League / Activity Group / organiser identifier where exposed
- location/store identifier where exposed

Discord routes target the PokEvent record or the preserved upstream identifier,
not a display name such as "Atomic Cards". Aliases are presentation/search aids,
not primary keys.

## Discord routing

A route belongs to one Discord guild and one channel. A route can constrain:

- League/Activity Group
- location/store
- game (TCG, VGC, GO)
- geographic radius

Populated constraints are combined with AND semantics.

## Upstream resilience

The public Play! Pokémon Event Locator currently uses anti-bot protection.
PokEvent will not attempt to defeat CAPTCHA or other active anti-bot controls.
The source adapter will target the underlying event data interface if it is
available for normal browser use. The local catalogue remains available if the
upstream service is temporarily unavailable.

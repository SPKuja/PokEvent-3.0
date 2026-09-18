from urllib.parse import urlencode

from pokevent.domain import EventSearch, EventSnapshot

from .base import EventSource, EventSourceError


class PlayPokemonSource(EventSource):
    """Play! Pokémon Event Locator adapter.

    The public locator is protected by anti-bot controls, so 3.0 deliberately
    keeps locator discovery separate from the rest of the application. We will
    implement this adapter against the locator's underlying data endpoint once
    its stable response shape has been verified.
    """

    name = "play_pokemon"
    locator_base_url = "https://events.pokemon.com/"

    @classmethod
    def locator_url(cls, search: EventSearch) -> str:
        params = {
            "latitude": search.latitude,
            "longitude": search.longitude,
            "range": search.radius_miles,
        }
        return f"{cls.locator_base_url}?{urlencode(params)}"

    async def fetch_events(self, search: EventSearch) -> list[EventSnapshot]:
        raise EventSourceError(
            "Play! Pokémon ingestion is not enabled until the Event Locator data "
            "endpoint and stable identifiers have been verified."
        )

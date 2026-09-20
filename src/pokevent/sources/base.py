from abc import ABC, abstractmethod

from pokevent.domain import EventSearch, EventSnapshot


class EventSourceError(RuntimeError):
    pass


class EventSource(ABC):
    name: str

    @abstractmethod
    async def fetch_events(self, search: EventSearch) -> list[EventSnapshot]:
        raise NotImplementedError

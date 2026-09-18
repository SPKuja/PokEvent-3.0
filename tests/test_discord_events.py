from datetime import UTC, datetime

from pokevent.discord_bot import EVENTS_PAGE_SIZE, event_page_content
from pokevent.models import Event


def _event(index: int) -> Event:
    return Event(
        source="test",
        upstream_event_id=f"event-{index}",
        title=f"Event {index}",
        starts_at=datetime(2026, 9, 18 + index, 12, 0, tzinfo=UTC),
        content_hash=f"hash-{index}",
    )


def test_event_page_content_paginates_upcoming_events() -> None:
    rows = [_event(index) for index in range(EVENTS_PAGE_SIZE + 2)]

    first = event_page_content(rows, 0)
    second = event_page_content(rows, 1)

    assert "**Event 0**" in first
    assert "**Event 9**" in first
    assert "**Event 10**" not in first
    assert "Page **1/2**" in first

    assert "**Event 10**" in second
    assert "**Event 11**" in second
    assert "Page **2/2**" in second

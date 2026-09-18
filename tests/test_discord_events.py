from datetime import UTC, datetime

from pokevent.discord_bot import (
    EVENTS_PAGE_SIZE,
    _event_embed,
    _event_link_view,
    _event_location,
    _official_event_url,
    event_page_content,
)
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

    first = event_page_content(rows, 0, "Test events")
    second = event_page_content(rows, 1, "Test events")

    assert "### Test events" in first
    assert "**Event 0**" in first
    assert "**Event 9**" in first
    assert "**Event 10**" not in first
    assert "Page **1/2**" in first

    assert "**Event 10**" in second
    assert "**Event 11**" in second
    assert "Page **2/2**" in second


def test_event_card_is_spaced_into_large_sections() -> None:
    event = _event(0)
    event.game = "tcg"
    event.event_type = "League Challenge"
    event.venue_name = "The Incredible Comic Shop"
    event.city = "Swindon"
    event.postcode = "SN1 1LF"
    event.address = "None None 21 THE PLAZA, BRUNEL CENTRE, ENGLAND SN1 1LF, GB"
    event.source_url = (
        "https://www.pokemon.com/us/pokemon-trainer-club/"
        "play-pokemon-tournaments/26-09-021255/"
    )
    event.registration_url = "https://example.com/register"

    embed = _event_embed(event, "Pokémon League Swindon", preview=True)
    view = _event_link_view(event)
    description = embed.description or ""

    assert embed.url == event.source_url
    assert "### 🧪 Test preview" in description
    assert "### 🎟️ Event" in description
    assert "### 📅 When" in description
    assert "### 📍 Where" in description
    assert "━━━━━━━━━━━━━━━━━━━━" in description
    assert "Pokémon TCG · League Challenge · Pokémon League Swindon" in description
    assert "**The Incredible Comic Shop**" in description
    assert "None None" not in description
    assert "21 THE PLAZA" in description
    assert view is not None
    assert len(view.children) == 2


def test_event_location_cleans_null_placeholders() -> None:
    event = _event(0)
    event.venue_name = "THE INCREDIBLE COMIC SHOP"
    event.city = "Swindon"
    event.address = "None None 21 THE PLAZA, BRUNEL CENTRE"

    location = _event_location(event)

    assert location is not None
    assert "None" not in location
    assert "21 THE PLAZA" in location
    assert "Swindon" in location


def test_generic_pokemon_locator_url_is_not_used_as_event_link() -> None:
    event = _event(0)
    event.source_url = "https://www.pokemon.com/play-pokemon-tournaments//"

    assert _official_event_url(event) is None
    assert _event_link_view(event) is None

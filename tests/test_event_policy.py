from pokevent.event_policy import (
    CARD_EVENT_TYPES,
    DEFAULT_CARD_EVENT_TYPES,
    effective_card_event_types,
    event_card_type,
)


def test_default_card_policy_prioritises_tournaments() -> None:
    assert "League Session" not in DEFAULT_CARD_EVENT_TYPES
    assert "Playtime" not in DEFAULT_CARD_EVENT_TYPES
    assert "Friendly Tournament" in DEFAULT_CARD_EVENT_TYPES
    assert "League Challenge" in DEFAULT_CARD_EVENT_TYPES
    assert "League Cup" in DEFAULT_CARD_EVENT_TYPES
    assert "Pre-Release" in DEFAULT_CARD_EVENT_TYPES
    assert "Other / Unknown" in DEFAULT_CARD_EVENT_TYPES


def test_event_card_type_normalises_known_categories() -> None:
    assert event_card_type("League Session") == "League Session"
    assert event_card_type("Friendly Tournament") == "Friendly Tournament"
    assert event_card_type("League Challenge") == "League Challenge"
    assert event_card_type("TCG League Cup") == "League Cup"
    assert event_card_type("Prerelease") == "Pre-Release"
    assert event_card_type("Pokémon Playtime") == "Playtime"
    assert event_card_type("Something New") == "Other / Unknown"


def test_explicit_empty_card_policy_disables_all_cards() -> None:
    assert effective_card_event_types([]) == set()
    assert effective_card_event_types(None) == set(DEFAULT_CARD_EVENT_TYPES)
    assert set(CARD_EVENT_TYPES).issuperset(DEFAULT_CARD_EVENT_TYPES)

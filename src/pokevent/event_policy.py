from __future__ import annotations

CARD_EVENT_TYPES = (
    "League Session",
    "Friendly Tournament",
    "League Challenge",
    "League Cup",
    "Pre-Release",
    "Playtime",
    "Other / Unknown",
)

DEFAULT_CARD_EVENT_TYPES = frozenset(
    {
        "Friendly Tournament",
        "League Challenge",
        "League Cup",
        "Pre-Release",
        "Other / Unknown",
    }
)


def event_card_type(event_type: str | None) -> str:
    """Map a normalised/upstream event type to a stable Discord card category."""

    value = (event_type or "").strip().casefold()

    if value == "league session":
        return "League Session"
    if value == "friendly tournament":
        return "Friendly Tournament"
    if "league challenge" in value:
        return "League Challenge"
    if "league cup" in value:
        return "League Cup"
    if "pre-release" in value or "prerelease" in value:
        return "Pre-Release"
    if "playtime" in value:
        return "Playtime"
    return "Other / Unknown"


def effective_card_event_types(configured: list[str] | None) -> set[str]:
    if configured is None:
        return set(DEFAULT_CARD_EVENT_TYPES)
    return {value for value in configured if value in CARD_EVENT_TYPES}

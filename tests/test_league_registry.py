from datetime import UTC, datetime

from pokevent import worker
from pokevent.config import Settings
from pokevent.domain import EventSnapshot, Game
from pokevent.worker import apply_league_registry


def test_league_registry_is_json_environment_mapping(monkeypatch) -> None:
    monkeypatch.setenv(
        "POKEVENT_LEAGUES",
        '{"2012924":"Pokémon League Swindon","7654321":"Atomic Cards"}',
    )
    settings = Settings()

    assert settings.leagues["2012924"] == "Pokémon League Swindon"
    assert settings.leagues["7654321"] == "Atomic Cards"


def test_configured_league_name_overrides_venue_label(monkeypatch) -> None:
    monkeypatch.setattr(
        worker.settings,
        "leagues",
        {"2012924": "Pokémon League Swindon"},
    )

    snapshot = EventSnapshot(
        source="pokedata",
        upstream_event_id="event-guid",
        upstream_organisation_id="2012924",
        organisation_name="THE INCREDIBLE COMIC SHOP",
        venue_name="THE INCREDIBLE COMIC SHOP",
        title="Pokemon League Swindon - September League Challenge",
        game=Game.TCG,
        event_type="League Challenge",
        starts_at=datetime(2026, 9, 20, 11, 0, tzinfo=UTC),
    )

    updated = apply_league_registry(snapshot)

    assert updated.organisation_name == "Pokémon League Swindon"
    assert updated.venue_name == "THE INCREDIBLE COMIC SHOP"
    assert updated.upstream_organisation_id == "2012924"

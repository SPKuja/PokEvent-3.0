import inspect
from datetime import UTC, datetime

from pokevent import web
from pokevent.config import DEFAULT_LEAGUE_LOGOS, DEFAULT_LEAGUES, Settings
from pokevent.models import Event
from pokevent.public_site import public_index_html


def _event() -> Event:
    return Event(
        source="test",
        upstream_event_id="event-1",
        upstream_organisation_id="2012924",
        title="Example League Challenge",
        game="tcg",
        event_type="League Challenge",
        status="active",
        starts_at=datetime(2026, 9, 20, 11, 0, tzinfo=UTC),
        venue_name="Example Venue",
        city="Swindon",
        content_hash="hash",
    )


def test_public_site_contains_calendar_and_list_controls() -> None:
    html = public_index_html(
        community_name="Pokémon League Swindon",
        home_name="Swindon",
    )

    assert "<h1>PokÈvent</h1>" in html
    assert "configured Play! Pokémon Leagues in and around Swindon" in html
    assert 'id="calendarMode"' in html
    assert 'id="listMode"' in html
    assert 'id="leagueFilter"' in html


def test_public_event_payload_uses_configured_league_branding(monkeypatch) -> None:
    monkeypatch.setattr(
        web.settings,
        "leagues",
        {"2012924": "Pokémon League Swindon"},
    )
    monkeypatch.setattr(
        web.settings,
        "league_logos",
        {"2012924": "https://example.com/swindon.png"},
    )

    payload = web._public_event_payload(_event(), "Upstream League Name")

    assert payload["league_name"] == "Pokémon League Swindon"
    assert payload["league_logo"] == "https://example.com/swindon.png"
    assert payload["league_id"] == "2012924"


def test_public_logo_rejects_non_http_url(monkeypatch) -> None:
    monkeypatch.setattr(
        web.settings,
        "league_logos",
        {"2012924": "javascript:alert(1)"},
    )

    assert web._public_logo_url("2012924") is None



def test_default_leagues_have_matching_public_logos() -> None:
    assert DEFAULT_LEAGUES == {
        "2012924": "Pokémon League Swindon",
        "5683200": "Bath TCG",
        "6234115": "Firestorm Games Swindon",
        "6244670": "Crazy Collectables",
        "6238080": "Atomic Cards",
    }
    assert set(DEFAULT_LEAGUE_LOGOS) == set(DEFAULT_LEAGUES)
    assert DEFAULT_LEAGUE_LOGOS["2012924"].endswith(
        "/pokemon_league_swindon.png"
    )
    assert DEFAULT_LEAGUE_LOGOS["5683200"].endswith("/bath_tcg.png")
    assert DEFAULT_LEAGUE_LOGOS["6234115"].endswith("/firestorm.png")
    assert DEFAULT_LEAGUE_LOGOS["6244670"].endswith("/crazy_collectables.jpg")
    assert DEFAULT_LEAGUE_LOGOS["6238080"].endswith("/atomic_cards.png")



def test_public_event_surfaces_default_to_configured_leagues_only() -> None:
    event_parameters = inspect.signature(web.upcoming_events).parameters
    calendar_parameters = inspect.signature(web.calendar_feed).parameters

    assert event_parameters["configured_only"].default is True
    assert calendar_parameters["configured_only"].default is True


def test_portainer_league_environment_can_override_defaults(monkeypatch) -> None:
    monkeypatch.setenv(
        "POKEVENT_LEAGUES",
        '{"9999999":"Example League"}',
    )

    configured = Settings(_env_file=None)

    assert configured.leagues == {"9999999": "Example League"}

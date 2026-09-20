import inspect
from datetime import UTC, datetime

from pokevent import web
from pokevent.bot_info_site import bot_info_html
from pokevent.config import (
    DEFAULT_BRAND_LOGO_URL,
    DEFAULT_LEAGUE_LOGOS,
    DEFAULT_LEAGUES,
    Settings,
)
from pokevent.models import BotRuntime, Event
from pokevent.public_site import public_index_html
from pokevent.search_site import search_page_html


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
        brand_logo_url=DEFAULT_BRAND_LOGO_URL,
    )

    assert "<h1>PokÈvent</h1>" in html
    assert 'class="brand-logo"' in html
    assert DEFAULT_BRAND_LOGO_URL in html
    assert "Upcoming events from our configured" not in html
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



def test_brand_logo_can_be_overridden_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "POKEVENT_BRAND_LOGO_URL",
        "https://example.com/custom-brand.png",
    )

    configured = Settings(_env_file=None)

    assert configured.brand_logo_url == "https://example.com/custom-brand.png"


def test_safe_public_url_rejects_non_http_brand_url() -> None:
    assert web._safe_public_url("javascript:alert(1)") is None



def test_bot_info_page_has_live_stats_and_invite_control() -> None:
    html = bot_info_html(
        community_name="Pokémon League Swindon",
        brand_logo_url=DEFAULT_BRAND_LOGO_URL,
    )

    assert "PokÈvent Discord Bot" in html
    assert 'id="uptime"' in html
    assert 'id="servers"' in html
    assert 'id="inviteButton"' in html
    assert 'href="/"' in html


def test_bot_info_payload_reports_online_runtime() -> None:
    runtime = BotRuntime(
        id="discord",
        bot_user_id="123456789",
        bot_name="PokÈvent#0001",
        avatar_url="https://cdn.discordapp.com/avatars/123/avatar.png",
        guild_count=7,
        started_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
        last_seen_at=datetime(2026, 9, 20, 9, 59, 30, tzinfo=UTC),
    )

    payload = web._bot_info_payload(
        runtime,
        now=datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
    )

    assert payload["online"] is True
    assert payload["uptime_seconds"] == 7200
    assert payload["server_count"] == 7
    assert payload["bot_name"] == "PokÈvent#0001"
    assert payload["avatar_url"] == "https://cdn.discordapp.com/avatars/123/avatar.png"
    assert "client_id=123456789" in payload["invite_url"]
    assert "applications.commands" in payload["invite_url"]


def test_bot_info_payload_marks_stale_heartbeat_offline() -> None:
    runtime = BotRuntime(
        id="discord",
        bot_user_id="123456789",
        bot_name="PokÈvent#0001",
        guild_count=7,
        started_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
        last_seen_at=datetime(2026, 9, 20, 9, 55, tzinfo=UTC),
    )

    payload = web._bot_info_payload(
        runtime,
        now=datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
    )

    assert payload["online"] is False
    assert payload["uptime_seconds"] == 6900



def test_public_pages_use_consistent_width_and_navigation() -> None:
    calendar_html = public_index_html(
        community_name="Pokémon League Swindon",
        brand_logo_url=DEFAULT_BRAND_LOGO_URL,
    )
    bot_html = bot_info_html(
        community_name="Pokémon League Swindon",
        brand_logo_url=DEFAULT_BRAND_LOGO_URL,
    )
    search_html = search_page_html(
        community_name="Pokémon League Swindon",
        brand_logo_url=DEFAULT_BRAND_LOGO_URL,
    )

    for html in (calendar_html, bot_html, search_html):
        assert "width:min(1180px" in html
        assert 'href="/search"' in html
        assert 'href="/bot"' in html


def test_bot_info_page_lists_public_commands() -> None:
    html = bot_info_html(
        community_name="Pokémon League Swindon",
        brand_logo_url=DEFAULT_BRAND_LOGO_URL,
    )

    assert "/events [league]" in html
    assert "/calendar" in html
    assert "/pokevent setup" in html
    assert "/pokevent status" in html
    assert 'id="botAvatar"' in html


def test_search_page_supports_location_queries() -> None:
    html = search_page_html(
        community_name="Pokémon League Swindon",
        brand_logo_url=DEFAULT_BRAND_LOGO_URL,
    )

    assert "Find Pokémon events" in html
    assert "town, postcode, venue or address" in html
    assert 'id="searchForm"' in html
    assert "/api/search?q=" in html


def test_search_value_normalises_spaces_and_escapes_wildcards() -> None:
    normalised, pattern = web._search_value("  SN1   1AA%  ")

    assert normalised == "SN1 1AA%"
    assert pattern == r"%SN1 1AA\%%"

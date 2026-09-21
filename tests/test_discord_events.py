from datetime import UTC, datetime
from types import SimpleNamespace

import discord
from PIL import Image

from pokevent.discord_bot import (
    ANNOUNCEMENT_CHANNEL_TYPES,
    EVENTS_PAGE_SIZE,
    POKEMON_WELCOME_MESSAGES,
    SetupDashboardView,
    WelcomeManagerView,
    _event_announcement_mentions,
    _event_cleanup_at,
    _event_embed,
    _event_link_view,
    _event_location,
    _event_snapshot,
    _event_update_notice,
    _official_event_url,
    _public_calendar_url,
    _render_welcome_banner,
    _summary_embed,
    _thread_name,
    _welcome_message,
    bot,
    event_page_content,
)
from pokevent.models import Event, GuildLeague


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


def test_event_thread_name_is_bounded_to_discord_limit() -> None:
    event = _event(0)
    event.title = "Very long event title " * 20

    name = _thread_name(event)

    assert name.startswith("Event discussion · ")
    assert len(name) <= 100


def test_event_cleanup_uses_fallback_duration_and_grace(monkeypatch) -> None:
    from pokevent import discord_bot

    monkeypatch.setattr(discord_bot.settings, "event_default_duration_hours", 8)
    monkeypatch.setattr(discord_bot.settings, "event_cleanup_grace_hours", 2)

    event = _event(0)
    event.starts_at = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    event.ends_at = None

    assert _event_cleanup_at(event) == datetime(
        2026,
        9,
        20,
        20,
        0,
        tzinfo=UTC,
    )


def test_event_cleanup_prefers_known_end_time(monkeypatch) -> None:
    from pokevent import discord_bot

    monkeypatch.setattr(discord_bot.settings, "event_default_duration_hours", 8)
    monkeypatch.setattr(discord_bot.settings, "event_cleanup_grace_hours", 2)

    event = _event(0)
    event.starts_at = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    event.ends_at = datetime(2026, 9, 20, 15, 30, tzinfo=UTC)

    assert _event_cleanup_at(event) == datetime(
        2026,
        9,
        20,
        17,
        30,
        tzinfo=UTC,
    )



def test_summary_only_contains_configured_leagues() -> None:
    swindon = GuildLeague(
        guild_id="guild-1",
        name="Pokémon League Swindon",
        name_key="pokémon league swindon",
        league_id="2012924",
        origin="service",
    )
    bath = GuildLeague(
        guild_id="guild-1",
        name="Bath TCG",
        name_key="bath tcg",
        league_id="5683200",
        origin="service",
    )

    swindon_event = _event(0)
    swindon_event.upstream_organisation_id = "2012924"
    swindon_event.game = "tcg"

    unrelated = _event(1)
    unrelated.title = "Unrelated nearby event"
    unrelated.upstream_organisation_id = "9999999"

    embed = _summary_embed(
        [swindon, bath],
        [swindon_event, unrelated],
        "2012924",
    )
    rendered = str(embed.to_dict())

    assert "Pokémon League Swindon" in rendered
    assert "Bath TCG" in rendered
    assert "Unrelated nearby event" not in rendered



def test_admin_commands_are_consolidated_under_pokevent_setup() -> None:
    top_level = {command.name: command for command in bot.tree.get_commands()}

    assert "events" in top_level
    assert "pokevent" in top_level
    assert "league" not in top_level
    assert "eventchannel" not in top_level

    pokevent = top_level["pokevent"]
    subcommands = {command.name for command in pokevent.commands}
    assert subcommands == {"setup", "status"}



def test_cancelled_event_card_is_visibly_marked_and_not_registerable() -> None:
    event = _event(0)
    event.status = "cancelled"
    event.registration_url = "https://example.com/register"
    event.source_url = (
        "https://www.pokemon.com/us/pokemon-trainer-club/"
        "play-pokemon-tournaments/26-09-CANCELLED/"
    )

    embed = _event_embed(event, "Example League")
    view = _event_link_view(event)
    description = embed.description or ""

    assert embed.title is not None
    assert embed.title.startswith("❌ CANCELLED")
    assert "### ❌ Event cancelled" in description
    assert view is not None
    assert len(view.children) == 1
    assert view.children[0].label == "View on Pokémon"


def test_event_update_notice_lists_meaningful_changes() -> None:
    event = _event(0)
    event.status = "active"
    event.venue_name = "Old Venue"
    previous = _event_snapshot(event)

    event.starts_at = datetime(2026, 9, 21, 18, 30, tzinfo=UTC)
    event.venue_name = "New Venue"
    event.address = "1 Example Street"
    event.city = "Exampletown"

    notice = _event_update_notice(previous, event)

    assert "### 🔄 Event details updated" in notice
    assert "**Date/time:**" in notice
    assert "**Venue:** Old Venue → New Venue" in notice
    assert "**Location:** Not specified → 1 Example Street · Exampletown" in notice


def test_event_update_notice_calls_out_cancellation() -> None:
    event = _event(0)
    event.status = "active"
    previous = _event_snapshot(event)

    event.status = "cancelled"
    notice = _event_update_notice(previous, event)

    assert notice.startswith("### ❌ Event cancelled")


def test_event_update_notice_handles_legacy_publication_without_snapshot() -> None:
    event = _event(0)
    event.status = "cancelled"

    notice = _event_update_notice(None, event)

    assert "### ❌ Event cancelled" in notice
    assert "announcement card has been updated" in notice



def test_event_notifications_default_to_no_ping() -> None:
    config = SimpleNamespace(
        event_mention_mode=None,
        event_mention_role_ids=None,
    )
    channel = SimpleNamespace(guild=SimpleNamespace(me=None))

    content, allowed = _event_announcement_mentions(config, channel)

    assert content is None
    assert allowed.everyone is False
    assert allowed.roles is False
    assert allowed.users is False


def test_event_notifications_can_ping_everyone_when_permitted() -> None:
    config = SimpleNamespace(
        event_mention_mode="everyone",
        event_mention_role_ids=None,
    )
    guild = SimpleNamespace(me=object())
    channel = SimpleNamespace(
        guild=guild,
        permissions_for=lambda _member: SimpleNamespace(mention_everyone=True),
    )

    content, allowed = _event_announcement_mentions(config, channel)

    assert content == "@everyone"
    assert allowed.everyone is True


def test_welcome_message_replaces_supported_tokens() -> None:
    member = SimpleNamespace(
        mention="<@123>",
        display_name="Example Trainer",
        guild=SimpleNamespace(name="Example Pokémon Server"),
    )

    message = _welcome_message(
        member,
        "Hello {member}! Welcome to {server}, {display_name}.",
    )

    assert message == (
        "Hello <@123>! Welcome to Example Pokémon Server, Example Trainer."
    )


def test_generated_welcome_banner_is_png() -> None:
    buffer = _render_welcome_banner(
        member_name="Example Trainer",
        server_name="Example Pokémon Server",
    )

    with Image.open(buffer) as image:
        assert image.format == "PNG"
        assert image.size == (1200, 400)



def test_random_pokemon_welcome_is_used_without_custom_message(monkeypatch) -> None:
    from pokevent import discord_bot

    member = SimpleNamespace(
        mention="<@123>",
        display_name="Example Trainer",
        guild=SimpleNamespace(name="Example Pokémon Server"),
    )
    monkeypatch.setattr(
        discord_bot.random,
        "choice",
        lambda messages: messages[0],
    )

    message = _welcome_message(member, None)

    assert message == (
        "A wild <@123> appeared! Welcome to **Example Pokémon Server**! ✨"
    )


def test_pokemon_welcome_pool_has_variety() -> None:
    assert len(POKEMON_WELCOME_MESSAGES) >= 10
    assert len(set(POKEMON_WELCOME_MESSAGES)) == len(POKEMON_WELCOME_MESSAGES)


def test_welcome_manager_warns_when_member_listener_is_disabled(monkeypatch) -> None:
    from pokevent import discord_bot

    monkeypatch.setattr(discord_bot.settings, "enable_member_welcomes", False)

    view = WelcomeManagerView(
        invoker_id=1,
        guild_id="guild-1",
        mode="text",
        channel_id="123",
        message=None,
    )

    assert "Member join listener is disabled" in view.content()
    assert "POKEVENT_ENABLE_MEMBER_WELCOMES=true" in view.content()



def test_channel_pickers_allow_discord_announcement_channels() -> None:
    assert discord.ChannelType.text in ANNOUNCEMENT_CHANNEL_TYPES
    assert discord.ChannelType.news in ANNOUNCEMENT_CHANNEL_TYPES



def test_public_calendar_url_uses_configured_base_url(monkeypatch) -> None:
    from pokevent import discord_bot

    monkeypatch.setattr(
        discord_bot.settings,
        "public_base_url",
        "https://events.example.com/pokevent/",
    )

    assert _public_calendar_url() == "https://events.example.com/pokevent/"


def test_public_calendar_url_rejects_invalid_base_url(monkeypatch) -> None:
    from pokevent import discord_bot

    monkeypatch.setattr(
        discord_bot.settings,
        "public_base_url",
        "not-a-url",
    )

    assert _public_calendar_url() is None



def test_portainer_enables_member_welcomes_by_default() -> None:
    from pathlib import Path

    compose = Path("docker-compose.portainer.yml").read_text(encoding="utf-8")

    assert (
        "POKEVENT_ENABLE_MEMBER_WELCOMES: "
        "${POKEVENT_ENABLE_MEMBER_WELCOMES:-true}"
    ) in compose


def test_admin_dashboard_has_manual_event_check() -> None:
    dashboard = SetupDashboardView(invoker_id=1, guild_id="guild-1")
    labels = {
        item.label
        for item in dashboard.children
        if isinstance(item, discord.ui.Button)
    }

    assert "Check New Events" in labels
    assert "Community Events" not in labels

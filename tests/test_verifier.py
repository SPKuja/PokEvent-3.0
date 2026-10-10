from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pokevent.catalogue import upsert_snapshots
from pokevent.domain import EventSnapshot
from pokevent.models import Base, Event, VerificationCheckpoint, VerificationRecord
from pokevent.verifier import (
    apply_verified_snapshots,
    official_tournament_id,
    run_daily_verification,
)


def snapshot(*, league: str = "2012924", identifier: str = "26-10-007632"):
    return EventSnapshot(
        source="pokedata",
        upstream_event_id="9618324d-b6db-4389-bf4c-c883d87953c8",
        upstream_organisation_id=league,
        title="Pokemon League Swindon - Friendly Tournament",
        status="active",
        starts_at=datetime(2026, 10, 18, 11, tzinfo=UTC),
        country="GB",
        source_url=(
            "https://www.pokemon.com/us/pokemon-trainer-club/"
            f"play-pokemon-tournaments/{identifier}/"
        ),
        upstream_payload={"Display_id": None},
    )


@pytest.mark.asyncio
async def test_verifier_corrects_cancelled_event_and_override_survives_sync() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 10, 10, tzinfo=UTC)
    event = snapshot()

    calls = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        league_id = request.url.path.split("/")[2]
        assert league_id == "2012924"
        return httpx.Response(
            200,
            json={
                "league_id": league_id,
                "events": [
                    {
                        "league_id": league_id,
                        "tournament_id": "26-10-007632",
                        "status": "cancelled",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        args = dict(
            feed_url="https://approved.example/leagues/{league_id}/events",
            token=None,
            league_ids={"2012924"},
            client=client,
            now=now,
        )
        assert await run_daily_verification(sessions, **args) == (1, 1)
        assert await run_daily_verification(
            sessions, **(args | {"now": now + timedelta(hours=23)})
        ) == (0, 0)
        assert len(calls) == 1

    assert official_tournament_id(event) == "26-10-007632"

    async with sessions() as session:
        corrected = (await apply_verified_snapshots(session, [event]))[0]
        assert corrected.status == "cancelled"
        assert corrected.title == event.title
        first = await upsert_snapshots(session, [corrected])
        assert first.created == 1

        # Reapplying the same Pokédata row must NOT resurrect it.
        corrected_again = (await apply_verified_snapshots(session, [event]))[0]
        assert corrected_again.status == "cancelled"
        second = await upsert_snapshots(session, [corrected_again])
        assert second.unchanged == 1

        stored = await session.scalar(select(Event))
        assert stored is not None
        assert stored.status == "cancelled"
    await engine.dispose()


@pytest.mark.asyncio
async def test_verifier_updates_fields_and_restores_reactivated_event() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 10, 10, tzinfo=UTC)
    state = {"status": "cancelled"}

    def transport(request: httpx.Request) -> httpx.Response:
        league_id = request.url.path.split("/")[2]
        return httpx.Response(
            200,
            json={
                "league_id": league_id,
                "events": [
                    {
                        "league_id": league_id,
                        "tournament_id": "26-10-007632",
                        "status": state["status"],
                        "title": "Verified name",
                        "starts_at": "2026-10-19T13:00:00+01:00",
                        "venue_name": "Verified venue",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        args = dict(
            feed_url="https://approved.example/leagues/{league_id}/events",
            token="secret",
            league_ids={"2012924"},
            client=client,
        )
        assert await run_daily_verification(sessions, **(args | {"now": now})) == (1, 1)
        async with sessions() as session:
            confirmed = (await apply_verified_snapshots(session, [snapshot()]))[0]
            assert confirmed.title == "Verified name"
            assert confirmed.venue_name == "Verified venue"
            assert confirmed.starts_at == datetime(2026, 10, 19, 13, tzinfo=confirmed.starts_at.tzinfo)
            assert confirmed.status == "cancelled"

        state["status"] = "active"
        assert await run_daily_verification(
            sessions, **(args | {"now": now + timedelta(hours=25)})
        ) == (1, 1)
        async with sessions() as session:
            confirmed = (await apply_verified_snapshots(session, [snapshot()]))[0]
            assert confirmed.status == "active"
    await engine.dispose()


@pytest.mark.asyncio
async def test_feed_failure_does_not_commit_partial_results() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    def transport(request: httpx.Request) -> httpx.Response:
        league_id = request.url.path.split("/")[2]
        if league_id == "5683200":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "league_id": league_id,
                "events": [
                    {
                        "league_id": league_id,
                        "tournament_id": "26-10-007632",
                        "status": "cancelled",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await run_daily_verification(
                sessions,
                feed_url="https://approved.example/leagues/{league_id}/events",
                token=None,
                league_ids={"2012924", "5683200"},
                client=client,
            )
    async with sessions() as session:
        assert (await session.scalars(select(VerificationRecord))).all() == []
        assert (await session.scalars(select(VerificationCheckpoint))).all() == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_missing_entries_do_not_infer_cancellation() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def transport(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"league_id": "2012924", "events": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        assert await run_daily_verification(
            sessions,
            feed_url="https://approved.example/leagues/{league_id}/events",
            token=None,
            league_ids={"2012924"},
            client=client,
        ) == (0, 0)
    async with sessions() as session:
        assert (await apply_verified_snapshots(session, [snapshot()]))[0].status == "active"
    await engine.dispose()


@pytest.mark.asyncio
async def test_disabled_verifier_and_unapproved_urls_are_safe() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    assert await run_daily_verification(
        sessions, feed_url=None, token=None, league_ids={"2012924"}
    ) == (0, 0)
    with pytest.raises(ValueError, match="HTTPS"):
        await run_daily_verification(
            sessions,
            feed_url="http://example.com/leagues/{league_id}/events",
            token=None,
            league_ids={"2012924"},
        )
    assert official_tournament_id(snapshot(identifier="26-10-023392")) == "26-10-023392"
    await engine.dispose()

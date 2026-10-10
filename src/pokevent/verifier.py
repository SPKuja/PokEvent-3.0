"""Optional once-daily verification against an *authorised*, independent feed.

This module does NOT scrape Pokémon websites or claim an official Pokémon API.
A trusted administrator must configure a permitted HTTPS source with the
documented JSON format. Without one, verification safely remains disabled.

Only explicitly returned statuses and fields are overlaid. Absence, failed
requests and incomplete feeds never imply cancellation.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .domain import EventSnapshot, EventStatus
from .models import VerificationCheckpoint, VerificationRecord

log = logging.getLogger("pokevent.verifier")
TOURNAMENT_ID = re.compile(r"(?<![0-9])([0-9]{2}-[0-9]{2}-[0-9]{6})(?![0-9])")
ALLOWED_STATUSES = {"active", "cancelled"}
MAX_EVENTS_PER_LEAGUE = 500


def official_tournament_id(snapshot: EventSnapshot) -> str | None:
    """Use Pokémon's tournament ID, never a Pokédata GUID, for reconciliation."""
    payload = snapshot.upstream_payload or {}
    for value in (
        payload.get("Display_id"),
        snapshot.source_url,
        payload.get("pokemon_url"),
    ):
        if not isinstance(value, str):
            continue
        match = TOURNAMENT_ID.search(value)
        if match:
            return match.group(1)
    return None


def _validate_feed_url(template: str) -> None:
    if template.count("{league_id}") != 1:
        raise ValueError("Verification URL must contain exactly one {league_id}")
    parsed = urlparse(template.replace("{league_id}", "2012924"))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        raise ValueError("Verification requires an HTTPS URL without user info")
    if parsed.fragment:
        raise ValueError("Verification URL must not have a fragment")


def _normalise_event(raw: Any, league_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Verification feed contained a non-object event")
    if raw.get("league_id") != league_id:
        raise ValueError("Verification feed contains an event from another league")
    tournament_id = raw.get("tournament_id")
    if not isinstance(tournament_id, str) or not TOURNAMENT_ID.fullmatch(
        tournament_id
    ):
        raise ValueError("Verification event is missing a valid tournament ID")

    status = raw.get("status")
    if not isinstance(status, str) or status.lower() not in ALLOWED_STATUSES:
        raise ValueError(f"Unrecognised verification status for {tournament_id}")
    status = status.lower()

    title = raw.get("title")
    venue_name = raw.get("venue_name")
    for name, value, maximum in (
        ("title", title, 500),
        ("venue_name", venue_name, 255),
    ):
        if value is not None and (
            not isinstance(value, str) or not value.strip() or len(value) > maximum
        ):
            raise ValueError(f"Invalid {name} in verified {tournament_id}")

    starts_at: datetime | None = None
    if raw.get("starts_at") is not None:
        value = raw["starts_at"]
        if not isinstance(value, str):
            raise ValueError(f"Invalid starts_at in verified {tournament_id}")
        try:
            starts_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid starts_at in verified {tournament_id}") from exc
        if starts_at.tzinfo is None:
            raise ValueError("Verified start time needs an explicit UTC offset")

    return {
        "league_id": league_id,
        "tournament_id": tournament_id,
        "status": status,
        "title": title,
        "starts_at": starts_at,
        "venue_name": venue_name,
    }


async def fetch_league_verification(
    client: httpx.AsyncClient,
    *,
    url_template: str,
    league_id: str,
    token: str | None = None,
) -> list[dict[str, Any]]:
    _validate_feed_url(url_template)
    if not league_id.isdigit():
        raise ValueError("League ID must be numeric")

    url = url_template.replace("{league_id}", quote(league_id, safe=""))
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = await client.get(url, headers=headers)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or body.get("league_id") != league_id:
        raise ValueError("Verification feed league ID mismatch")
    rows = body.get("events")
    if not isinstance(rows, list) or len(rows) > MAX_EVENTS_PER_LEAGUE:
        raise ValueError("Verification feed has missing or oversized events")
    # The explicit list is authoritative for the fields in returned entries.
    # Missing entries are NOT treated as cancelled.
    parsed = [_normalise_event(row, league_id) for row in rows]
    ids = [row["tournament_id"] for row in parsed]
    if len(ids) != len(set(ids)):
        raise ValueError("Verification feed has duplicate tournament IDs")
    return parsed


async def apply_verified_snapshots(
    session: AsyncSession,
    snapshots: list[EventSnapshot],
) -> list[EventSnapshot]:
    """Overlay independent verification before normal catalogue hash/upsert."""
    keys = {
        (snapshot.upstream_organisation_id, tournament_id)
        for snapshot in snapshots
        if (tournament_id := official_tournament_id(snapshot))
        and snapshot.upstream_organisation_id
    }
    if not keys:
        return snapshots

    league_ids = {league_id for league_id, _ in keys}
    records = (
        await session.scalars(
            select(VerificationRecord).where(
                VerificationRecord.league_id.in_(league_ids)
            )
        )
    ).all()
    verified = {
        (row.league_id, row.tournament_id): row
        for row in records
        if (row.league_id, row.tournament_id) in keys
    }
    result: list[EventSnapshot] = []
    for snapshot in snapshots:
        tournament_id = official_tournament_id(snapshot)
        row = verified.get((snapshot.upstream_organisation_id, tournament_id))
        if row is None:
            result.append(snapshot)
            continue
        patch: dict[str, Any] = {"status": EventStatus(row.status)}
        if row.title is not None:
            patch["title"] = row.title
        if row.starts_at is not None:
            patch["starts_at"] = row.starts_at
        if row.venue_name is not None:
            patch["venue_name"] = row.venue_name
        result.append(snapshot.model_copy(update=patch))
    return result


async def run_daily_verification(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    feed_url: str | None,
    token: str | None,
    league_ids: set[str],
    interval_hours: int = 24,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Poll each configured league at most daily and save explicit corrections.

    All league lookups must succeed before any corrections or the checkpoint
    are committed. A failed fetch does not suppress the next retry.
    """
    if not feed_url:
        return 0, 0
    _validate_feed_url(feed_url)
    if interval_hours < 24:
        raise ValueError("Verification must run no more frequently than daily")

    now = now or datetime.now(UTC)
    async with session_factory() as session:
        checkpoint = await session.get(VerificationCheckpoint, "daily")
        if checkpoint:
            last = checkpoint.last_success_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if now - last < timedelta(hours=interval_hours):
                return 0, 0

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=25, follow_redirects=False)
    try:
        all_rows: list[dict[str, Any]] = []
        for league_id in sorted(league_ids):
            rows = await fetch_league_verification(
                client, url_template=feed_url, league_id=league_id, token=token
            )
            all_rows.extend(rows)
    finally:
        if owns_client:
            await client.aclose()

    changed = 0
    async with session_factory() as session:
        # Recheck under the same transaction before writing; the worker
        # normally has only one instance, with manual checks read-only.
        checkpoint = await session.get(VerificationCheckpoint, "daily")
        if checkpoint:
            last = checkpoint.last_success_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if now - last < timedelta(hours=interval_hours):
                return 0, 0

        for row in all_rows:
            record = await session.scalar(
                select(VerificationRecord).where(
                    VerificationRecord.league_id == row["league_id"],
                    VerificationRecord.tournament_id == row["tournament_id"],
                )
            )
            if record is None:
                record = VerificationRecord(**row, verified_at=now)
                session.add(record)
                changed += 1
            else:
                if any(getattr(record, key) != row[key] for key in
                       ("status", "title", "starts_at", "venue_name")):
                    changed += 1
                for key in ("status", "title", "starts_at", "venue_name"):
                    setattr(record, key, row[key])
                record.verified_at = now

        if checkpoint is None:
            session.add(VerificationCheckpoint(id="daily", last_success_at=now))
        else:
            checkpoint.last_success_at = now
        await session.commit()

    log.info(
        "verification complete leagues=%s explicit_events=%s changed=%s",
        len(league_ids), len(all_rows), changed,
    )
    return len(all_rows), changed

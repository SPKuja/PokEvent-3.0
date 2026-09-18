from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Game(StrEnum):
    TCG = "tcg"
    VGC = "vgc"
    GO = "go"
    OTHER = "other"


class EventStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class EventSearch(BaseModel):
    latitude: float
    longitude: float
    radius_miles: float = Field(gt=0, le=250)
    starts_after: datetime | None = None


class EventSnapshot(BaseModel):
    source: str
    upstream_event_id: str
    upstream_organisation_id: str | None = None
    upstream_location_id: str | None = None

    title: str
    game: Game | None = None
    event_type: str | None = None
    status: EventStatus = EventStatus.ACTIVE

    starts_at: datetime
    ends_at: datetime | None = None

    organisation_name: str | None = None
    venue_name: str | None = None
    address: str | None = None
    city: str | None = None
    postcode: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    source_url: str | None = None
    registration_url: str | None = None
    upstream_payload: dict | None = None

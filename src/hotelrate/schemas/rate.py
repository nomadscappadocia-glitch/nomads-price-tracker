from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Platform(str, Enum):
    TRIP = "trip"
    BOOKING = "booking"
    GOOGLE_HOTELS = "google_hotels"
    AGODA = "agoda"


class SearchRequest(BaseModel):
    platform_hotel_id: str
    checkin: date
    checkout: date
    adults: int = Field(default=2, ge=1, le=8)
    children: int = Field(default=0, ge=0, le=6)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    platform_url: str | None = None


class RawRateOffer(BaseModel):
    platform: Platform
    platform_hotel_id: str
    room_name: str
    meal_plan: str | None = None
    cancellation_policy: str | None = None
    currency: str = Field(min_length=3, max_length=3)
    base_price: Decimal = Field(default=Decimal("0"))
    tax_fee: Decimal = Field(default=Decimal("0"))
    final_price: Decimal
    checkin: date
    checkout: date
    adults: int
    children: int
    source_url: str | None = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class NormalizedSnapshot(BaseModel):
    mapping_id: UUID
    platform: Platform
    room_name: str
    meal_plan: str | None = None
    cancellation_policy: str | None = None
    currency: str
    base_price: Decimal
    tax_fee: Decimal
    final_price: Decimal
    checkin: date
    checkout: date
    adults: int
    children: int
    source_url: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    scraped_at: datetime
    rate_hash: str

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field

from hotelrate.schemas.rate import Platform


class LiveQuoteRequest(BaseModel):
    hotel_name: str = Field(min_length=2)
    city: str = Field(default="")
    checkin: date
    checkout: date
    adults: int = Field(default=2, ge=1, le=8)
    children: int = Field(default=0, ge=0, le=6)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    platforms: list[Platform] | None = None
    known_urls: dict[str, str] = Field(default_factory=dict)
    probe_days_ahead: int = Field(default=12, ge=0, le=30)
    probe_step_days: int = Field(default=3, ge=1, le=7)


class LiveOffer(BaseModel):
    room_name: str
    final_price: Decimal
    base_price: Decimal
    tax_fee: Decimal
    currency: str
    meal_plan: str | None = None
    cancellation_policy: str | None = None
    source_url: str | None = None
    mode: str = "parsed"


class LiveAttempt(BaseModel):
    url: str
    checkin: date
    checkout: date
    offer_count: int
    structured_offer_count: int
    modes: list[str] = Field(default_factory=list)
    diagnosis: str = ""


class LivePlatformResult(BaseModel):
    platform: Platform
    selected_url: str | None = None
    selected_checkin: date | None = None
    selected_checkout: date | None = None
    offer_count: int = 0
    structured_offer_count: int = 0
    diagnosis: str = ""
    offers: list[LiveOffer] = Field(default_factory=list)
    attempts: list[LiveAttempt] = Field(default_factory=list)


class LiveQuoteResponse(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request: LiveQuoteRequest
    results: list[LivePlatformResult] = Field(default_factory=list)


class BatchQuoteRequest(BaseModel):
    """批量爬取请求"""
    hotels: list[LiveQuoteRequest] = Field(min_length=1, max_length=50)
    concurrency: int = Field(default=3, ge=1, le=10, description="并发爬取的酒店数量")


class BatchQuoteResponse(BaseModel):
    """批量爬取响应"""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_hotels: int
    successful: int
    failed: int
    results: list[LiveQuoteResponse] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)

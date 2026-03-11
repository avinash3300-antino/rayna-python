"""
Pydantic v2 models — API DTOs and validation schemas.
Database tables are defined in app/memory/models.py (SQLAlchemy ORM).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────
# Database Document Shapes (validation / serialization)
# ─────────────────────────────────────────────────────────


class ConversationDoc(BaseModel):
    """conversations collection — one doc per chat session."""

    session_id: str
    title: str = "New Conversation"
    message_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MessageDoc(BaseModel):
    """messages collection — every user input and AI reply."""

    session_id: str
    role: str  # "user" | "assistant"
    content: str
    tourCarousel: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversionDoc(BaseModel):
    """conversions collection — every currency conversion performed."""

    session_id: str
    amount: float
    fromCurrency: str
    toCurrency: str
    convertedAmount: float
    exchangeRate: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("fromCurrency", "toCurrency", mode="before")
    @classmethod
    def uppercase_currency(cls, v: str) -> str:
        return v.upper() if isinstance(v, str) else v


# ─────────────────────────────────────────────────────────
# API Request / Response DTOs (replaces Zod schemas)
# ─────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """POST /api/chat body — mirrors ChatRequestSchema (Zod)."""

    message: str = Field(..., min_length=1, max_length=1000)
    session_id: str | None = None

    @field_validator("message", mode="before")
    @classmethod
    def strip_message(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


class ChatResponse(BaseModel):
    message: str
    session_id: str
    tourCarousel: dict[str, Any] | None = None
    productCarousel: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: str
    details: str | None = None


class HistoryMessage(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]


class PaginationMeta(BaseModel):
    total: int
    page: int
    limit: int
    pages: int


# ─────────────────────────────────────────────────────────
# Tour Card DTOs (replaces tour-card.dto.ts)
# ─────────────────────────────────────────────────────────


class TourCard(BaseModel):
    id: str
    title: str
    slug: str
    image: str
    location: str
    category: str
    originalPrice: float | None = None
    currentPrice: float
    currency: str
    discount: float | None = None
    discountPercentage: float | None = None
    isRecommended: bool | None = None
    isNew: bool | None = None
    rPoints: int | None = None
    rating: float | None = None
    reviewCount: int | None = None
    duration: str | None = None
    highlights: list[str] | None = None
    url: str


class TourCarousel(BaseModel):
    type: str = "tour_carousel"
    title: str
    subtitle: str | None = None
    cards: list[TourCard]
    totalResults: int | None = None


# ─────────────────────────────────────────────────────────
# Visa DTOs (replaces visa.dto.ts)
# ─────────────────────────────────────────────────────────


class VisaProduct(BaseModel):
    id: str
    name: str
    country: str
    countrySlug: str
    city: str
    type: str = "visas"
    productCategory: str
    visaType: str
    processingTime: str
    validity: str
    stayPeriod: str
    entryType: str
    normalPrice: float
    salePrice: float
    currency: str
    url: str
    image: str
    slug: str
    description: str
    requirements: list[str]
    isPopular: bool


class VisaResponse(BaseModel):
    success: bool
    count: int
    rawData: dict[str, Any]
    products: list[VisaProduct]

"""
Motor async repositories for all 3 MongoDB collections.
Replaces Mongoose models: Conversation, Message, Conversion.
Same collection names, same field names.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# Module-level db reference set during app lifespan
_db: AsyncIOMotorDatabase | None = None


def set_database(db: AsyncIOMotorDatabase | None) -> None:
    global _db
    _db = db


def get_database() -> AsyncIOMotorDatabase | None:
    return _db


def is_db_connected() -> bool:
    return _db is not None


# ─────────────────────────────────────────────────────────
# ConversationRepository
# ─────────────────────────────────────────────────────────


class ConversationRepository:
    @staticmethod
    def _col():  # type: ignore[no-untyped-def]
        if _db is None:
            return None
        return _db["conversations"]

    @classmethod
    async def upsert(cls, session_id: str, title: str) -> None:
        col = cls._col()
        if col is None:
            return
        try:
            now = datetime.now(timezone.utc)
            await col.update_one(
                {"session_id": session_id},
                {
                    "$setOnInsert": {
                        "session_id": session_id,
                        "title": title[:60],
                        "created_at": now,
                    },
                    "$inc": {"message_count": 1},
                    "$set": {"updated_at": now},
                },
                upsert=True,
            )
        except Exception:
            logger.exception("[DB] Failed to upsert conversation")

    @classmethod
    async def increment_count(cls, session_id: str) -> None:
        col = cls._col()
        if col is None:
            return
        try:
            await col.update_one(
                {"session_id": session_id},
                {"$inc": {"message_count": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            )
        except Exception:
            logger.exception("[DB] Failed to update conversation count")

    @classmethod
    async def get_by_session(cls, session_id: str) -> dict[str, Any] | None:
        col = cls._col()
        if col is None:
            return None
        return await col.find_one({"session_id": session_id})

    @classmethod
    async def list_all(cls, limit: int = 20, page: int = 1) -> tuple[list[dict[str, Any]], int]:
        col = cls._col()
        if col is None:
            return [], 0
        skip = (page - 1) * limit
        cursor = (
            col.find(
                {},
                {"session_id": 1, "title": 1, "message_count": 1, "created_at": 1, "updated_at": 1},
            )
            .sort("updated_at", -1)
            .skip(skip)
            .limit(limit)
        )
        conversations = await cursor.to_list(length=limit)
        total = await col.count_documents({})
        return conversations, total

    @classmethod
    async def delete_by_session(cls, session_id: str) -> None:
        col = cls._col()
        if col is None:
            return
        await col.delete_one({"session_id": session_id})


# ─────────────────────────────────────────────────────────
# MessageRepository
# ─────────────────────────────────────────────────────────


class MessageRepository:
    @staticmethod
    def _col():  # type: ignore[no-untyped-def]
        if _db is None:
            return None
        return _db["messages"]

    @classmethod
    async def save(
        cls,
        session_id: str,
        role: str,
        content: str,
        tour_carousel: dict[str, Any] | None = None,
    ) -> None:
        col = cls._col()
        if col is None:
            return
        try:
            await col.insert_one(
                {
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "tourCarousel": tour_carousel,
                    "timestamp": datetime.now(timezone.utc),
                }
            )
        except Exception:
            logger.exception("[DB] Failed to save %s message", role)

    @classmethod
    async def get_history(
        cls, session_id: str, limit: int = 50, page: int = 1
    ) -> tuple[list[dict[str, Any]], int]:
        col = cls._col()
        if col is None:
            return [], 0
        skip = (page - 1) * limit
        cursor = (
            col.find(
                {"session_id": session_id},
                {"role": 1, "content": 1, "tourCarousel": 1, "timestamp": 1},
            )
            .sort("timestamp", 1)
            .skip(skip)
            .limit(limit)
        )
        messages = await cursor.to_list(length=limit)
        total = await col.count_documents({"session_id": session_id})
        return messages, total

    @classmethod
    async def delete_by_session(cls, session_id: str) -> None:
        col = cls._col()
        if col is None:
            return
        await col.delete_many({"session_id": session_id})


# ─────────────────────────────────────────────────────────
# ConversionRepository
# ─────────────────────────────────────────────────────────


class ConversionRepository:
    @staticmethod
    def _col():  # type: ignore[no-untyped-def]
        if _db is None:
            return None
        return _db["conversions"]

    @classmethod
    async def save(
        cls,
        session_id: str,
        amount: float,
        from_currency: str,
        to_currency: str,
        converted_amount: float,
        exchange_rate: float,
    ) -> None:
        col = cls._col()
        if col is None:
            return
        try:
            await col.insert_one(
                {
                    "session_id": session_id,
                    "amount": amount,
                    "fromCurrency": from_currency.upper(),
                    "toCurrency": to_currency.upper(),
                    "convertedAmount": converted_amount,
                    "exchangeRate": exchange_rate,
                    "timestamp": datetime.now(timezone.utc),
                }
            )
        except Exception:
            logger.exception("[DB] Failed to save conversion")

    @classmethod
    async def get_by_session(cls, session_id: str) -> list[dict[str, Any]]:
        col = cls._col()
        if col is None:
            return []
        cursor = (
            col.find(
                {"session_id": session_id},
                {
                    "amount": 1, "fromCurrency": 1, "toCurrency": 1,
                    "convertedAmount": 1, "exchangeRate": 1, "timestamp": 1,
                },
            )
            .sort("timestamp", -1)
        )
        return await cursor.to_list(length=200)

    @classmethod
    async def list_all(cls, limit: int = 20, page: int = 1) -> tuple[list[dict[str, Any]], int]:
        col = cls._col()
        if col is None:
            return [], 0
        skip = (page - 1) * limit
        cursor = col.find().sort("timestamp", -1).skip(skip).limit(limit)
        conversions = await cursor.to_list(length=limit)
        total = await col.count_documents({})
        return conversions, total

    @classmethod
    async def delete_by_session(cls, session_id: str) -> None:
        col = cls._col()
        if col is None:
            return
        await col.delete_many({"session_id": session_id})

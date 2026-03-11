"""
SQLAlchemy async repositories for all 3 PostgreSQL tables.
Replaces Motor/MongoDB repositories. Same class names and method signatures.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.memory.database import get_session_factory
from app.memory.database import is_db_connected as _is_db_connected
from app.memory.models import Conversation, Conversion, Message

logger = logging.getLogger(__name__)


def is_db_connected() -> bool:
    """Re-export so callers don't need to change imports."""
    return _is_db_connected()


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy ORM row to a plain dict."""
    if hasattr(row, "__table__"):
        return {c.key: getattr(row, c.key) for c in row.__table__.columns}
    return dict(row._mapping) if hasattr(row, "_mapping") else {}


# ─────────────────────────────────────────────────────────
# ConversationRepository
# ─────────────────────────────────────────────────────────


class ConversationRepository:
    @classmethod
    async def upsert(cls, session_id: str, title: str) -> None:
        factory = get_session_factory()
        if factory is None:
            return
        try:
            async with factory() as session:
                now = datetime.now(timezone.utc)
                stmt = pg_insert(Conversation).values(
                    session_id=session_id,
                    title=title[:60],
                    message_count=1,
                    created_at=now,
                    updated_at=now,
                ).on_conflict_do_update(
                    index_elements=["session_id"],
                    set_={
                        "message_count": Conversation.message_count + 1,
                        "updated_at": now,
                    },
                )
                await session.execute(stmt)
                await session.commit()
        except Exception:
            logger.exception("[DB] Failed to upsert conversation")

    @classmethod
    async def increment_count(cls, session_id: str) -> None:
        factory = get_session_factory()
        if factory is None:
            return
        try:
            async with factory() as session:
                stmt = (
                    update(Conversation)
                    .where(Conversation.session_id == session_id)
                    .values(
                        message_count=Conversation.message_count + 1,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await session.execute(stmt)
                await session.commit()
        except Exception:
            logger.exception("[DB] Failed to update conversation count")

    @classmethod
    async def get_by_session(cls, session_id: str) -> dict[str, Any] | None:
        factory = get_session_factory()
        if factory is None:
            return None
        async with factory() as session:
            stmt = select(Conversation).where(Conversation.session_id == session_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return _row_to_dict(row) if row else None

    @classmethod
    async def list_all(cls, limit: int = 20, page: int = 1) -> tuple[list[dict[str, Any]], int]:
        factory = get_session_factory()
        if factory is None:
            return [], 0
        offset = (page - 1) * limit
        async with factory() as session:
            stmt = (
                select(Conversation)
                .order_by(Conversation.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            count_stmt = select(func.count()).select_from(Conversation)
            total = (await session.execute(count_stmt)).scalar() or 0

        return [_row_to_dict(r) for r in rows], total

    @classmethod
    async def delete_by_session(cls, session_id: str) -> None:
        factory = get_session_factory()
        if factory is None:
            return
        async with factory() as session:
            await session.execute(
                delete(Conversation).where(Conversation.session_id == session_id)
            )
            await session.commit()


# ─────────────────────────────────────────────────────────
# MessageRepository
# ─────────────────────────────────────────────────────────


class MessageRepository:
    @classmethod
    async def save(
        cls,
        session_id: str,
        role: str,
        content: str,
        tour_carousel: dict[str, Any] | None = None,
    ) -> None:
        factory = get_session_factory()
        if factory is None:
            return
        try:
            async with factory() as session:
                msg = Message(
                    session_id=session_id,
                    role=role,
                    content=content,
                    tour_carousel=tour_carousel,
                    timestamp=datetime.now(timezone.utc),
                )
                session.add(msg)
                await session.commit()
        except Exception:
            logger.exception("[DB] Failed to save %s message", role)

    @classmethod
    async def get_history(
        cls, session_id: str, limit: int = 50, page: int = 1
    ) -> tuple[list[dict[str, Any]], int]:
        factory = get_session_factory()
        if factory is None:
            return [], 0
        offset = (page - 1) * limit
        async with factory() as session:
            stmt = (
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.timestamp.asc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            count_stmt = (
                select(func.count())
                .select_from(Message)
                .where(Message.session_id == session_id)
            )
            total = (await session.execute(count_stmt)).scalar() or 0

        # Map to match previous API field names
        messages = []
        for r in rows:
            d = _row_to_dict(r)
            d["tourCarousel"] = d.pop("tour_carousel", None)
            messages.append(d)
        return messages, total

    @classmethod
    async def delete_by_session(cls, session_id: str) -> None:
        factory = get_session_factory()
        if factory is None:
            return
        async with factory() as session:
            await session.execute(
                delete(Message).where(Message.session_id == session_id)
            )
            await session.commit()


# ─────────────────────────────────────────────────────────
# ConversionRepository
# ─────────────────────────────────────────────────────────


class ConversionRepository:
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
        factory = get_session_factory()
        if factory is None:
            return
        try:
            async with factory() as session:
                conv = Conversion(
                    session_id=session_id,
                    amount=amount,
                    from_currency=from_currency.upper(),
                    to_currency=to_currency.upper(),
                    converted_amount=converted_amount,
                    exchange_rate=exchange_rate,
                    timestamp=datetime.now(timezone.utc),
                )
                session.add(conv)
                await session.commit()
        except Exception:
            logger.exception("[DB] Failed to save conversion")

    @classmethod
    async def get_by_session(cls, session_id: str) -> list[dict[str, Any]]:
        factory = get_session_factory()
        if factory is None:
            return []
        async with factory() as session:
            stmt = (
                select(Conversion)
                .where(Conversion.session_id == session_id)
                .order_by(Conversion.timestamp.desc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        conversions = []
        for r in rows:
            d = _row_to_dict(r)
            d["fromCurrency"] = d.pop("from_currency", "")
            d["toCurrency"] = d.pop("to_currency", "")
            d["convertedAmount"] = d.pop("converted_amount", 0.0)
            d["exchangeRate"] = d.pop("exchange_rate", 0.0)
            conversions.append(d)
        return conversions

    @classmethod
    async def list_all(cls, limit: int = 20, page: int = 1) -> tuple[list[dict[str, Any]], int]:
        factory = get_session_factory()
        if factory is None:
            return [], 0
        offset = (page - 1) * limit
        async with factory() as session:
            stmt = (
                select(Conversion)
                .order_by(Conversion.timestamp.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            count_stmt = select(func.count()).select_from(Conversion)
            total = (await session.execute(count_stmt)).scalar() or 0

        conversions = []
        for r in rows:
            d = _row_to_dict(r)
            d["fromCurrency"] = d.pop("from_currency", "")
            d["toCurrency"] = d.pop("to_currency", "")
            d["convertedAmount"] = d.pop("converted_amount", 0.0)
            d["exchangeRate"] = d.pop("exchange_rate", 0.0)
            conversions.append(d)
        return conversions, total

    @classmethod
    async def delete_by_session(cls, session_id: str) -> None:
        factory = get_session_factory()
        if factory is None:
            return
        async with factory() as session:
            await session.execute(
                delete(Conversion).where(Conversion.session_id == session_id)
            )
            await session.commit()

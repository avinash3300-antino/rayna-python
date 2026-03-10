"""
History API — replaces src/history/history.router.ts.
GET    /api/history
GET    /api/history/:sessionId
DELETE /api/history/:sessionId
GET    /api/history/:sessionId/conversions
GET    /api/history/conversions/all
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.memory.repositories import (
    ConversationRepository,
    ConversionRepository,
    MessageRepository,
    is_db_connected,
)

router = APIRouter(prefix="/api/history", tags=["history"])


def _serialize_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Make a MongoDB document JSON-safe (ObjectId, datetime, etc.)."""
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            doc[key] = str(value)
        elif isinstance(value, datetime):
            doc[key] = value.isoformat()
        elif isinstance(value, dict):
            doc[key] = _serialize_doc(value)
        elif isinstance(value, list):
            doc[key] = [_serialize_doc(v) if isinstance(v, dict) else
                        v.isoformat() if isinstance(v, datetime) else
                        str(v) if isinstance(v, ObjectId) else v
                        for v in value]
    return doc


def _require_db() -> JSONResponse | None:
    if not is_db_connected():
        return JSONResponse(
            status_code=503,
            content={"error": "Database not connected. Configure MONGODB_URI to enable history."},
        )
    return None


@router.get("/")
async def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    page: int = Query(default=1, ge=1),
) -> JSONResponse:
    err = _require_db()
    if err:
        return err
    try:
        conversations, total = await ConversationRepository.list_all(limit, page)
        conversations = [_serialize_doc(c) for c in conversations]
        return JSONResponse(
            status_code=200,
            content={
                "conversations": conversations,
                "pagination": {
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "pages": math.ceil(total / limit) if limit else 0,
                },
            },
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("[HistoryRouter] GET /history error")
        return JSONResponse(status_code=500, content={"error": "Failed to fetch conversations."})


@router.get("/conversions/all")
async def all_conversions(
    limit: int = Query(default=20, ge=1, le=100),
    page: int = Query(default=1, ge=1),
) -> JSONResponse:
    err = _require_db()
    if err:
        return err
    try:
        conversions, total = await ConversionRepository.list_all(limit, page)
        conversions = [_serialize_doc(c) for c in conversions]
        return JSONResponse(
            status_code=200,
            content={
                "conversions": conversions,
                "pagination": {
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "pages": math.ceil(total / limit) if limit else 0,
                },
            },
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("[HistoryRouter] GET /conversions/all error")
        return JSONResponse(status_code=500, content={"error": "Failed to fetch conversions."})


@router.get("/{session_id}/conversions")
async def session_conversions(session_id: str) -> JSONResponse:
    err = _require_db()
    if err:
        return err
    try:
        conversions = await ConversionRepository.get_by_session(session_id)
        conversions = [_serialize_doc(c) for c in conversions]
        return JSONResponse(
            status_code=200,
            content={"session_id": session_id, "conversions": conversions},
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("[HistoryRouter] GET conversions error")
        return JSONResponse(status_code=500, content={"error": "Failed to fetch conversions."})


@router.get("/{session_id}")
async def get_conversation(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    page: int = Query(default=1, ge=1),
) -> JSONResponse:
    err = _require_db()
    if err:
        return err
    try:
        conversation = await ConversationRepository.get_by_session(session_id)
        if not conversation:
            return JSONResponse(status_code=404, content={"error": "Conversation not found."})

        messages, total = await MessageRepository.get_history(session_id, limit, page)
        messages = [_serialize_doc(m) for m in messages]
        conversation = _serialize_doc(conversation)

        return JSONResponse(
            status_code=200,
            content={
                "session_id": session_id,
                "title": conversation.get("title", ""),
                "created_at": conversation.get("created_at", ""),
                "messages": messages,
                "pagination": {
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "pages": math.ceil(total / limit) if limit else 0,
                },
            },
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("[HistoryRouter] GET /history/:sessionId error")
        return JSONResponse(status_code=500, content={"error": "Failed to fetch messages."})


@router.delete("/{session_id}")
async def delete_conversation(session_id: str) -> JSONResponse:
    err = _require_db()
    if err:
        return err
    try:
        import asyncio
        await asyncio.gather(
            ConversationRepository.delete_by_session(session_id),
            MessageRepository.delete_by_session(session_id),
            ConversionRepository.delete_by_session(session_id),
        )
        return JSONResponse(
            status_code=200,
            content={"success": True, "message": "Conversation deleted."},
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("[HistoryRouter] DELETE error")
        return JSONResponse(status_code=500, content={"error": "Failed to delete conversation."})

"""
POST /api/chat — replaces src/chat/chat.router.ts.
GET  /api/chat/history/:sessionId
DELETE /api/chat/session/:sessionId
GET  /api/chat/health
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.agent.graph import run_agent
from app.memory.session import SessionService
from app.models.schemas import ChatRequest, ChatResponse, ErrorResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Session service ref set during lifespan
_session_service: SessionService | None = None


def set_session_service(svc: SessionService) -> None:
    global _session_service
    _session_service = svc


@router.post("/", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> JSONResponse:
    """Main chat endpoint — rate limited via slowapi."""
    session_id = body.session_id or str(uuid.uuid4())

    try:
        result = await run_agent(session_id, body.message)
        return JSONResponse(
            status_code=200,
            content={
                "message": result["reply"],
                "session_id": session_id,
                "tourCarousel": result.get("tourCarousel"),
                "metadata": result.get("metadata"),
            },
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("[ChatRouter] Chat error")
        return JSONResponse(
            status_code=500,
            content={"error": "Something went wrong. Please try again.", "details": str(e)},
        )


@router.get("/history/{session_id}")
async def get_history(session_id: str, limit: int = 10) -> JSONResponse:
    assert _session_service is not None
    limit = min(max(limit, 1), 50)
    messages = _session_service.get_history(session_id, limit)
    formatted = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
    ]
    return JSONResponse(
        status_code=200,
        content={"session_id": session_id, "messages": formatted},
    )


@router.delete("/session/{session_id}")
async def clear_session(session_id: str) -> JSONResponse:
    assert _session_service is not None
    _session_service.delete(session_id)
    return JSONResponse(
        status_code=200,
        content={"success": True, "message": "Session cleared"},
    )


@router.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "service": "rayna-chatbot",
            "milestone": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

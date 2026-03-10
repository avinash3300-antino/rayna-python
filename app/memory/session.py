"""
In-memory session store with asyncio TTL eviction.
Replaces src/chat/session.service.ts exactly.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class Session:
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_activity: float = field(default_factory=time.time)
    user_id: str | None = None


class SessionService:
    """Python dict + asyncio background task replaces Map<sessionId, messages> + setInterval."""

    def __init__(self) -> None:
        settings = get_settings()
        self._sessions: dict[str, Session] = {}
        self._max_messages: int = settings.session_max_messages
        self._ttl_seconds: float = settings.session_ttl_minutes * 60
        self._cleanup_task: asyncio.Task[None] | None = None

    # ── Lifecycle ──────────────────────────────────────────

    def start_cleanup_loop(self) -> None:
        self._cleanup_task = asyncio.create_task(self._eviction_loop())

    async def stop_cleanup_loop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _eviction_loop(self) -> None:
        while True:
            await asyncio.sleep(10 * 60)  # every 10 minutes
            now = time.time()
            expired = [
                sid
                for sid, session in self._sessions.items()
                if now - session.last_activity > self._ttl_seconds
            ]
            for sid in expired:
                del self._sessions[sid]
            if expired:
                logger.info("[SessionService] Cleaned up %d expired sessions", len(expired))

    # ── Public API (mirrors Node.js SessionService) ────────

    def get_context(self, session_id: str) -> list[dict[str, Any]]:
        session = self._sessions.get(session_id)
        if not session:
            return []
        return session.messages[-self._max_messages :]

    def add_message(
        self,
        session_id: str,
        message: dict[str, Any],
        user_id: str | None = None,
    ) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            session = Session()
            self._sessions[session_id] = session
        session.messages.append(message)
        session.last_activity = time.time()
        if user_id:
            session.user_id = user_id
        # Cap at 50 messages (same as Node.js)
        if len(session.messages) > 50:
            session.messages = session.messages[-50:]

    def get_history(self, session_id: str, limit: int = 10) -> list[dict[str, str]]:
        session = self._sessions.get(session_id)
        if not session:
            return []
        result: list[dict[str, str]] = []
        for m in session.messages[-limit:]:
            content = m.get("content", "")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = " ".join(
                    block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
                )
            else:
                text = ""
            result.append({"role": m["role"], "content": text})
        return result

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

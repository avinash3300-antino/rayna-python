"""
FastAPI entrypoint — replaces api/index.ts + src/main.ts.
Lifespan event connects Motor to MongoDB (replaces Vercel cold-start singleton).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1 import chat as chat_router
from app.api.v1 import history as history_router
from app.api.v1 import rag as rag_router
from app.config import get_settings
from app.memory.repositories import set_database
from app.memory.session import SessionService
from app.middleware.rate_limit import create_limiter

# ── Structured logging ─────────────────────────────────────
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Module-level singletons ────────────────────────────────
session_service = SessionService()
limiter = create_limiter()


# ── Lifespan: connect/disconnect MongoDB, start/stop cleanup ─
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    # Connect to MongoDB via Motor
    db = None
    if settings.mongodb_uri and "<username>" not in settings.mongodb_uri:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient

            client = AsyncIOMotorClient(
                settings.mongodb_uri,
                serverSelectionTimeoutMS=5000,
            )
            # Ping to verify connection
            await client.admin.command("ping")
            db = client.get_default_database()
            if db is None:
                # Extract DB name from URI or default to "rayna"
                db = client["rayna"]
            set_database(db)
            logger.info("[DB] Connected to MongoDB")
        except Exception:
            logger.exception("[DB] Connection failed — history will not be persisted")
    else:
        logger.warning("[DB] MONGODB_URI not configured — history will not be persisted.")

    # Start session TTL cleanup
    session_service.start_cleanup_loop()

    # Initialise the agent graph
    from app.agent.graph import init_agent

    init_agent(session_service)

    # Wire session service into chat router
    chat_router.set_session_service(session_service)

    logger.info(
        "\n"
        "  ╔════════════════════════════════════════╗\n"
        "  ║   Rayna Tours Chatbot — Running         ║\n"
        "  ║                                        ║\n"
        "  ║   Port      : %s                    ║\n"
        "  ║   Env        : %s              ║\n"
        "  ║   LLM        : %s                  ║\n"
        "  ║   RAG        : %s               ║\n"
        "  ║   Milestone  : 1 (Tour Discovery + RAG) ║\n"
        "  ║                                        ║\n"
        "  ║   POST http://localhost:%s/api/chat  ║\n"
        "  ╚════════════════════════════════════════╝\n",
        settings.port,
        settings.node_env,
        settings.llm_provider.value,
        "Enabled" if settings.rag_enabled else "Disabled",
        settings.port,
    )

    yield

    # Cleanup
    await session_service.stop_cleanup_loop()
    set_database(None)
    logger.info("[App] Shutdown complete")


# ── FastAPI app ────────────────────────────────────────────
app = FastAPI(
    title="Rayna Tours Chatbot API",
    version="2.0.0",
    lifespan=lifespan,
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# ── Routes ─────────────────────────────────────────────────
app.include_router(chat_router.router)
app.include_router(history_router.router)
app.include_router(rag_router.router)


@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "name": "Rayna Tours Chatbot API",
            "version": "2.0.0",
            "milestone": 1,
            "status": "running",
            "endpoints": {
                "chat": "POST   /api/chat",
                "clear": "DELETE /api/chat/session/{sessionId}",
                "health": "GET    /api/chat/health",
                "ragStatus": "GET    /api/rag/status",
                "ragTest": "POST   /api/rag/test",
                "ragIngest": "POST   /api/rag/ingest",
                "ragSearch": "POST   /api/rag/search",
                "allConversations": "GET    /api/history",
                "conversationHistory": "GET    /api/history/{sessionId}",
                "deleteConversation": "DELETE /api/history/{sessionId}",
                "sessionConversions": "GET    /api/history/{sessionId}/conversions",
                "allConversions": "GET    /api/history/conversions/all",
            },
        },
    )


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(status_code=200, content={"status": "ok"})


# 404 fallback
@app.exception_handler(404)
async def not_found(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "Route not found"})


# Global error handler
@app.exception_handler(500)
async def internal_error(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("[App] Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})

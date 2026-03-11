"""
Redis cache for tool results — avoids repeated API calls for identical queries.
TTL-based expiry ensures data stays fresh.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


async def init_redis() -> None:
    """Connect to Redis. Called during app lifespan startup."""
    global _redis
    settings = get_settings()
    if not settings.redis_url:
        logger.warning("[Cache] REDIS_URL not configured — caching disabled")
        return
    try:
        _redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        await _redis.ping()
        logger.info("[Cache] Redis connected at %s", settings.redis_url)
    except Exception:
        logger.warning("[Cache] Redis connection failed — caching disabled")
        _redis = None


async def close_redis() -> None:
    """Disconnect from Redis. Called during app lifespan shutdown."""
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def _cache_key(tool_name: str, inp: dict[str, Any]) -> str:
    """Generate a deterministic cache key from tool name + input."""
    # Sort keys for consistent hashing
    payload = json.dumps({"tool": tool_name, "input": inp}, sort_keys=True)
    h = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"rayna:tool:{tool_name}:{h}"


# Tool-specific TTLs in seconds
TOOL_TTL: dict[str, int] = {
    "get_available_cities": 3600,       # 1 hour  — cities rarely change
    "get_all_products": 600,            # 10 min  — products update more often
    "get_city_products": 600,           # 10 min
    "get_city_holiday_packages": 600,   # 10 min
    "get_city_cruises": 600,            # 10 min
    "get_city_yachts": 600,             # 10 min
    "get_tour_cards": 300,              # 5 min   — cards with prices
    "get_product_details": 600,         # 10 min
    "get_visas": 3600,                  # 1 hour  — visa info is stable
    "get_popular_visas": 3600,          # 1 hour
    "convert_currency": 300,            # 5 min   — rates change
}

# Tools that should NOT be cached
NO_CACHE_TOOLS = set()  # all tools are cacheable for now


async def get_cached(tool_name: str, inp: dict[str, Any]) -> str | None:
    """Get cached tool result. Returns None on miss or if caching is disabled."""
    if _redis is None or tool_name in NO_CACHE_TOOLS:
        return None
    try:
        key = _cache_key(tool_name, inp)
        result = await _redis.get(key)
        if result:
            logger.debug("[Cache] HIT %s", key)
        return result
    except Exception:
        logger.debug("[Cache] Error reading cache for %s", tool_name)
        return None


async def set_cached(tool_name: str, inp: dict[str, Any], result: str) -> None:
    """Cache a tool result with appropriate TTL."""
    if _redis is None or tool_name in NO_CACHE_TOOLS:
        return
    try:
        key = _cache_key(tool_name, inp)
        ttl = TOOL_TTL.get(tool_name, 300)  # default 5 min
        await _redis.setex(key, ttl, result)
        logger.debug("[Cache] SET %s (TTL=%ds)", key, ttl)
    except Exception:
        logger.debug("[Cache] Error writing cache for %s", tool_name)

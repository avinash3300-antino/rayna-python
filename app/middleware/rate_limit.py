"""
Rate limiting — replaces src/common/rate-limiter.ts (express-rate-limit → slowapi).
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings


def create_limiter() -> Limiter:
    settings = get_settings()
    # Convert window_ms to a rate string: e.g. 20 per 60 seconds → "20/minute"
    window_seconds = settings.rate_limit_window_ms // 1000
    max_requests = settings.rate_limit_max_requests
    return Limiter(
        key_func=get_remote_address,
        default_limits=[f"{max_requests}/{window_seconds} seconds"],
    )

"""Rate limiting para /api/v1/agent/*/chat (Habeas Data: prevenir fuerza bruta)."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Any

# In-memory: IP -> [(timestamp, ...)]
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_BUCKET_TTL = 60  # 1 minuto


def _parse_rate_limit() -> int:
    """N req/min desde DUCKCLAW_RATE_LIMIT (ej. 30 o 30/minute)."""
    s = os.environ.get("DUCKCLAW_RATE_LIMIT", "30/minute").strip().lower()
    for part in s.split("/"):
        part = part.strip()
        if part.isdigit():
            return int(part)
    return 30


async def rate_limit_middleware(request: Any, call_next: Any):
    """
    Limita requests a /api/v1/agent/*/chat por IP.
    Solo aplica a POST /api/v1/agent/{id}/chat.
    """
    path = request.url.path or ""
    method = getattr(request, "method", "GET") or "GET"
    if method != "POST" or "/chat" not in path or "/api/v1/agent/" not in path:
        return await call_next(request)

    client = request.client
    ip = (client.host if client else "unknown") or "unknown"
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        ip = forwarded.split(",")[0].strip()

    max_per_min = _parse_rate_limit()
    now = time.monotonic()
    bucket = _rate_buckets[ip]
    bucket[:] = [t for t in bucket if now - t < _BUCKET_TTL]
    if len(bucket) >= max_per_min:
        from starlette.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
        )
    bucket.append(now)

    return await call_next(request)

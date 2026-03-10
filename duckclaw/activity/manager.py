"""
ActivityManager — registro de estados (IDLE, BUSY, WAITING) en Redis.

Spec: DuckClaw Production Readiness (Corto Plazo) — Orquestación.
Angular y n8n consultan GET /api/v1/activity/status para disponibilidad.
"""

from __future__ import annotations

import os
from typing import Any, Optional

STATE_KEY = "duckclaw:activity:state"
JOB_PREFIX = "duckclaw:activity:job:"
STATE_IDLE = "IDLE"
STATE_BUSY = "BUSY"
STATE_WAITING = "WAITING"


def _get_redis_url() -> str:
    return os.environ.get("REDIS_URL") or os.environ.get("ARQ_REDIS_URL") or "redis://localhost:6379"


class ActivityManager:
    """
    Gestiona estado de actividad en Redis: IDLE, BUSY, WAITING.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = (redis_url or _get_redis_url()).strip()
        self._redis: Any = None

    def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                import redis
                self._redis = redis.from_url(self.redis_url, decode_responses=True)
            except ImportError:
                raise RuntimeError("redis no instalado. Ejecuta: uv sync --extra queue")
        return self._redis

    def set_state(self, state: str) -> None:
        """Establece el estado global: IDLE, BUSY o WAITING."""
        r = self._get_redis()
        r.set(STATE_KEY, state)

    def get_state(self) -> str:
        """Obtiene el estado actual. Default IDLE si no hay Redis o clave."""
        try:
            r = self._get_redis()
            s = r.get(STATE_KEY)
            return (s or STATE_IDLE).upper()
        except Exception:
            return STATE_IDLE

    def set_job_result(self, job_id: str, result: str) -> None:
        """Guarda el resultado de un job para polling."""
        try:
            r = self._get_redis()
            r.setex(f"{JOB_PREFIX}{job_id}", 3600, result)  # TTL 1h
        except Exception:
            pass

    def get_job_result(self, job_id: str) -> Optional[str]:
        """Retorna el resultado del job si está listo."""
        try:
            r = self._get_redis()
            return r.get(f"{JOB_PREFIX}{job_id}")
        except Exception:
            return None

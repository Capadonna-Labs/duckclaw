"""Módulo de actividad: estado (IDLE/BUSY) y feed de conversaciones recientes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


def _get_db_path() -> str:
    from duckclaw.gateway_db import get_gateway_db_path
    return get_gateway_db_path()


def _get_db() -> Any:
    from duckclaw import DuckClaw
    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return DuckClaw(db_path)


@router.get("/status", summary="Estado de disponibilidad (IDLE/BUSY)")
async def get_activity_status():
    """
    Retorna el estado actual: IDLE, BUSY o WAITING.
    Si Redis está configurado, usa ActivityManager. Si no, retorna IDLE.
    """
    try:
        from duckclaw.activity.manager import ActivityManager
        mgr = ActivityManager()
        state = mgr.get_state()
        return {"status": state, "queue_available": True}
    except Exception:
        return {"status": "IDLE", "queue_available": False}


@router.get("/recent", summary="Actividades recientes de los agentes")
async def get_recent_activity(limit: int = 20):
    """
    Retorna los últimos turnos de chat (user + assistant) de todos los workers.
    Para mostrar en el dashboard Angular el feed de actividades.
    """
    db = _get_db()
    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS api_conversation (
                session_id VARCHAR NOT NULL,
                worker_id VARCHAR NOT NULL,
                role VARCHAR NOT NULL,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    except Exception:
        pass
    try:
        r = db.query(
            "SELECT session_id, worker_id, role, content, created_at FROM api_conversation "
            f"ORDER BY created_at DESC LIMIT {limit}"
        )
        rows = json.loads(r) if isinstance(r, str) else (r or [])
    except Exception:
        rows = []
    out = []
    for row in rows or []:
        out.append({
            "session_id": row.get("session_id", ""),
            "worker_id": row.get("worker_id", ""),
            "role": row.get("role", ""),
            "content": (row.get("content") or "")[:500],
            "created_at": str(row.get("created_at", "")),
        })
    return {"activities": out}

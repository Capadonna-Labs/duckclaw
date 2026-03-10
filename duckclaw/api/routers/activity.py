"""Activity router: estado (IDLE/BUSY/WAITING) y jobs en cola."""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])

_manager: Any = None


def _get_manager() -> Any:
    global _manager
    if _manager is None:
        try:
            from duckclaw.activity.manager import ActivityManager

            _manager = ActivityManager()
        except Exception:
            _manager = False
    return _manager


@router.get("/status", summary="Estado de disponibilidad")
async def get_activity_status():
    """
    Retorna el estado actual: IDLE, BUSY o WAITING.
    Para Angular y n8n consultar disponibilidad antes de enviar tareas.
    """
    manager = _get_manager()
    if not manager:
        return {"status": "IDLE", "queue_available": False}
    try:
        state = manager.get_state()
        return {"status": state, "queue_available": True}
    except Exception:
        return {"status": "IDLE", "queue_available": False}


class ChatQueueRequest(BaseModel):
    """Payload para POST /activity/chat/queue."""
    worker_id: str = Field(..., description="ID del worker")
    message: str = Field(..., description="Mensaje del usuario")
    session_id: str = Field("default", description="ID de sesión")
    history: list = Field(default_factory=list, description="Historial opcional")


@router.post("/chat/queue", summary="Encolar chat (ARQ)")
async def enqueue_chat(payload: ChatQueueRequest):
    """
    Encola un mensaje de chat en ARQ. Retorna job_id para polling.
    Requiere REDIS_URL y worker ARQ en ejecución.
    """
    redis_url = os.environ.get("REDIS_URL") or os.environ.get("ARQ_REDIS_URL")
    if not redis_url:
        raise HTTPException(
            status_code=503,
            detail="REDIS_URL no configurado. Usa POST /api/v1/agent/{worker_id}/chat para modo síncrono.",
        )
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        settings = RedisSettings(host="localhost", port=6379)
        if redis_url and redis_url.startswith("redis://"):
            parts = redis_url.replace("redis://", "").split("/")[0].split(":")
            settings = RedisSettings(host=parts[0], port=int(parts[1]) if len(parts) > 1 else 6379)
        pool = await create_pool(settings)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="arq no instalado. Ejecuta: uv sync --extra queue",
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Redis no disponible: {e}")

    try:
        job = await pool.enqueue_job(
            "run_chat_job",
            payload.worker_id,
            payload.message,
            payload.history or [],
            payload.session_id,
        )
        return {"job_id": job.job_id, "status": "queued"}
    finally:
        await pool.close()


@router.get("/job/{job_id}", summary="Resultado de job")
async def get_job_result(job_id: str):
    """Obtiene el resultado de un job de chat cuando está listo."""
    redis_url = os.environ.get("REDIS_URL") or os.environ.get("ARQ_REDIS_URL")
    if not redis_url:
        raise HTTPException(status_code=503, detail="REDIS_URL no configurado")
    try:
        from arq import create_pool
        from arq.jobs import Job
        from arq.connections import RedisSettings

        parts = redis_url.replace("redis://", "").split("/")[0].split(":")
        settings = RedisSettings(host=parts[0], port=int(parts[1]) if len(parts) > 1 else 6379)
        pool = await create_pool(settings)
        try:
            job = Job(job_id, pool)
            result = await job.result(timeout=0)
            return {"job_id": job_id, "status": "completed", "reply": str(result) if result is not None else ""}
        finally:
            await pool.close()
    except Exception as e:
        err = str(e).lower()
        if "not found" in err or "pending" in err or "timeout" in err or "arq" in err:
            return {"job_id": job_id, "status": "pending", "reply": None}
        raise HTTPException(status_code=500, detail=str(e))

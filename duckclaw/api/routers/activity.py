"""Activity router: agent status registry and real-time SSE stream.

Endpoints:
  GET  /api/v1/agents/status            → all workers' current status
  GET  /api/v1/agents/status/{worker_id} → single worker status
  POST /api/v1/agents/{worker_id}/heartbeat → heartbeat ping
  GET  /api/v1/agents/activity-stream   → SSE stream of state changes
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from duckclaw.api.activity import get_activity_manager, AgentStatus
from duckclaw.utils.sql_safe import is_safe_identifier

router = APIRouter(prefix="/api/v1/agents", tags=["activity"])


@router.get("/status", summary="Estado de todos los agentes")
async def get_agents_status():
    """Devuelve el estado de todos los workers registrados."""
    mgr = get_activity_manager()
    return mgr.get_all_statuses()


@router.get("/status/{worker_id}", summary="Estado de un agente")
async def get_agent_status(worker_id: str):
    """Devuelve el estado de un worker específico."""
    if not is_safe_identifier(worker_id):
        raise HTTPException(status_code=400, detail="worker_id inválido")
    mgr = get_activity_manager()
    return mgr.get_status(worker_id).to_dict()


@router.post("/{worker_id}/heartbeat", summary="Heartbeat ping")
async def agent_heartbeat(worker_id: str):
    """Envía un heartbeat para indicar que el agente sigue activo."""
    if not is_safe_identifier(worker_id):
        raise HTTPException(status_code=400, detail="worker_id inválido")
    mgr = get_activity_manager()
    ok = mgr.heartbeat(worker_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Agente no está en estado BUSY o WAITING")
    return {"status": "ok"}


@router.get("/activity-stream", summary="Stream SSE de cambios de estado")
async def activity_stream():
    """Emite eventos SSE en tiempo real cuando un agente cambia de estado.

    Uso: Angular se suscribe a este stream para actualizar el semáforo de
    disponibilidad en la UI.
    """
    mgr = get_activity_manager()
    return StreamingResponse(
        mgr.activity_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )

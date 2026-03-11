"""
ARQ worker — procesa jobs de chat en background.

Spec: DuckClaw Production Readiness (Corto Plazo).
Ejecutar: uv run arq duckclaw.activity.worker.WorkerSettings
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Optional

from arq.connections import RedisSettings


async def process_multimodal_input(
    ctx: dict,
    worker_id: str,
    thread_id: str,
    file_path: str,
    mime_type: str,
) -> str:
    """
    Job ARQ: transcribe audio o describe imagen, inyecta en agente, borra archivo (Habeas Data).
    """
    from pathlib import Path

    p = Path(file_path)
    is_audio = mime_type and "audio" in mime_type.lower()

    try:
        if is_audio:
            from duckclaw.multimodal import transcribe_audio
            text = transcribe_audio(file_path)
            wrapped = f"<audio_transcription>{text}</audio_transcription>" if text else "[Audio no transcrito]"
        else:
            from duckclaw.multimodal import describe_image
            text = describe_image(file_path)
            wrapped = f"<image_description>{text}</image_description>" if text else "[Imagen no descrita]"

        user_message = f"[El usuario envió un {'audio' if is_audio else 'medio'} que dice:] {wrapped}"

        result = await run_chat_job(ctx, worker_id, user_message, [], thread_id)
        return result
    finally:
        if p.is_file():
            try:
                p.unlink()
            except Exception:
                pass


async def run_chat_job(
    ctx: dict,
    worker_id: str,
    message: str,
    history: list,
    session_id: str = "default",
) -> str:
    """
    Job ARQ: invoca el grafo del worker y retorna la respuesta.
    """
    from duckclaw.activity.manager import ActivityManager, STATE_BUSY, STATE_IDLE, STATE_KEY
    from duckclaw.forge import AgentAssembler, WORKERS_TEMPLATES_DIR

    manager = ctx.get("activity_manager")
    if manager:
        manager.set_state(STATE_BUSY)

    try:
        manifest_path = WORKERS_TEMPLATES_DIR / worker_id / "manifest.yaml"
        if not manifest_path.is_file():
            return json.dumps({"error": f"Worker '{worker_id}' no encontrado"})

        from duckclaw.gateway_db import get_gateway_db_path
        db_path = get_gateway_db_path()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        graph = AgentAssembler.from_yaml(manifest_path).build(
            db=None,
            llm=None,
            db_path=db_path,
        )

        state = {"incoming": message, "history": history or [], "chat_id": session_id}
        loop = asyncio.get_event_loop()
        if hasattr(graph, "ainvoke"):
            result = await graph.ainvoke(state)
        else:
            result = await loop.run_in_executor(None, graph.invoke, state)

        reply = str(result.get("reply") or result.get("output") or "Sin respuesta.")
        try:
            from duckclaw.forge.homeostasis.notify import notify_ask_task

            notify_ask_task(worker_id=worker_id, session_id=session_id, trigger="task_complete")
        except Exception:
            pass
        return reply
    finally:
        if manager:
            manager.set_state(STATE_IDLE)


async def startup(ctx: dict) -> None:
    from duckclaw.activity.manager import ActivityManager

    ctx["activity_manager"] = ActivityManager()


async def shutdown(ctx: dict) -> None:
    from duckclaw.activity.manager import ActivityManager, STATE_IDLE

    manager = ctx.get("activity_manager")
    if manager:
        manager.set_state(STATE_IDLE)


def get_redis_settings() -> RedisSettings:
    url = os.environ.get("REDIS_URL") or os.environ.get("ARQ_REDIS_URL") or "redis://localhost:6379"
    url = url.strip()
    if url.startswith("redis://"):
        host = url.replace("redis://", "").split("/")[0].split(":")[0]
        port = 6379
        if ":" in url.replace("redis://", "").split("/")[0]:
            port = int(url.split(":")[-1].split("/")[0])
        return RedisSettings(host=host, port=port)
    return RedisSettings()


async def graph_lead_profiler_job(
    ctx: dict,
    worker_id: str,
    session_id: str,
    message: str,
    history: list,
    reply: str,
) -> int:
    """
    Job ARQ: extrae tripletas comerciales del chat y persiste en PGQ (Sovereign CRM).
    Spec: specs/Sovereign_CRM_Memoria_Bicameral_DuckDB_PGQ.md
    """
    from duckclaw.gateway_db import get_gateway_db_path
    db_path = get_gateway_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        from duckclaw import DuckClaw
        from duckclaw.forge.crm.lead_profiler import graph_lead_profiler
        from duckclaw.integrations.llm_providers import build_llm

        db = DuckClaw(db_path)
        provider = os.environ.get("DUCKCLAW_LLM_PROVIDER", "none_llm").strip().lower()
        model = os.environ.get("DUCKCLAW_LLM_MODEL", "").strip()
        base_url = os.environ.get("DUCKCLAW_LLM_BASE_URL", "").strip()
        llm = build_llm(provider, model, base_url) if provider != "none_llm" else None
        if llm is None:
            return 0

        chat_history = list(history or [])
        chat_history.append({"role": "user", "content": message})
        chat_history.append({"role": "assistant", "content": reply})
        return graph_lead_profiler(db, llm, chat_history, lead_id=session_id)
    except Exception:
        return 0


class WorkerSettings:
    """Configuración ARQ. Ejecutar: arq duckclaw.activity.worker.WorkerSettings"""
    functions = [run_chat_job, process_multimodal_input, graph_lead_profiler_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_redis_settings()

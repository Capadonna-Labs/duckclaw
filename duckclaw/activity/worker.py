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

        db_path = os.environ.get("DUCKCLAW_DB_PATH") or str(Path.cwd() / "db" / "gateway.duckdb")
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


class WorkerSettings:
    """Configuración ARQ. Ejecutar: arq duckclaw.activity.worker.WorkerSettings"""
    functions = [run_chat_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_redis_settings()

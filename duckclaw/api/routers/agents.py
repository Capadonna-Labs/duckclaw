"""Módulo de agentes: chat con streaming y historial."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

# Cache de grafos por worker_id (evitar rebuild en cada request)


@router.get("/workers", summary="Lista de workers virtuales disponibles")
async def list_workers():
    """Retorna los worker_id disponibles en templates/workers/."""
    from duckclaw.workers.factory import list_workers as _list_workers
    return {"workers": _list_workers()}
_graph_cache: dict[str, Any] = {}


def _get_db() -> Any:
    """DuckDB para api_conversation y workers."""
    from duckclaw import DuckClaw
    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return DuckClaw(db_path)


def _ensure_api_conversation_table(db: Any) -> None:
    """Crea tabla api_conversation si no existe."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS api_conversation (
            session_id VARCHAR NOT NULL,
            worker_id VARCHAR NOT NULL,
            role VARCHAR NOT NULL,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _get_db_path() -> str:
    """Ruta a la DB del gateway (api_conversation + workers)."""
    p = os.environ.get("DUCKCLAW_DB_PATH", "").strip()
    if p:
        return str(Path(p).resolve())
    return str(Path(__file__).resolve().parent.parent.parent.parent / "db" / "gateway.duckdb")


def _get_or_build_worker_graph(worker_id: str) -> Any:
    """Construye o recupera el grafo del worker desde cache."""
    if worker_id in _graph_cache:
        return _graph_cache[worker_id]
    from duckclaw.forge import AgentAssembler, WORKERS_TEMPLATES_DIR
    manifest_path = WORKERS_TEMPLATES_DIR / worker_id / "manifest.yaml"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' no encontrado")
    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    provider = os.environ.get("DUCKCLAW_LLM_PROVIDER", "").strip()
    model = os.environ.get("DUCKCLAW_LLM_MODEL", "").strip()
    base_url = os.environ.get("DUCKCLAW_LLM_BASE_URL", "").strip()

    graph = AgentAssembler.from_yaml(manifest_path).build(
        db=None,
        llm=None,
        db_path=db_path,
        llm_provider=provider if provider else None,
        llm_model=model if model else None,
        llm_base_url=base_url if base_url else None,
    )
    _graph_cache[worker_id] = graph
    return graph


async def _ainvoke(
    graph: Any, message: str, history: list, chat_id: str, metadata: Optional[dict[Any, Any]] = None
) -> str:
    """Invocación async del grafo (compatible con graph_server)."""
    # "input" va primero para que LangSmith muestre el mensaje del usuario en la columna Input (no el chat_id)
    state = {"input": message, "incoming": message, "history": history or [], "chat_id": chat_id}
    loop = asyncio.get_event_loop()
    
    metadata = metadata or {}
    channel = metadata.get("channel", "Api")
    username = metadata.get("username", "Unknown")
    
    clean_username = "".join(c if c.isalnum() else "_" for c in str(username))
    run_name_prefix = f"{str(channel).capitalize()}_{clean_username}_{chat_id}"
    
    full_metadata = {"session_id": chat_id, "thread_id": chat_id}
    full_metadata.update(metadata)
    
    config = {
        "configurable": {"thread_id": chat_id},
        "metadata": full_metadata,
        "run_name": "DuckClaw"
    }
    
    send_to_langsmith = os.environ.get("DUCKCLAW_SEND_TO_LANGSMITH", "false").lower() == "true"
    if send_to_langsmith:
        try:
            from langchain_core.tracers import LangChainTracer
            # Try to get project name from env, then graph spec
            spec = getattr(graph, "_worker_spec", None)
            project_name = os.environ.get("LANGCHAIN_PROJECT") or (getattr(spec, "name", "DuckClaw") if spec else "DuckClaw")
            config["callbacks"] = [LangChainTracer(project_name=project_name)]
        except Exception:
            pass

    if hasattr(graph, "ainvoke"):
        result = await graph.ainvoke(state, config=config)
    else:
        result = await loop.run_in_executor(None, graph.invoke, state, config)
    return str(result.get("reply") or result.get("output") or "Sin respuesta.")


def _safe_sql(s: str) -> str:
    """Escapa comillas simples para SQL."""
    return (s or "").replace("'", "''")[:256]


def _sanitize_for_telegram(text: str) -> str:
    """Quita Markdown que Telegram no interpreta bien: ## ### #### y líneas ---."""
    if not text or not isinstance(text, str):
        return text
    lines = text.split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped in ("---", "***", "___"):
            continue
        cleaned = re.sub(r"^#+\s*", "", line.lstrip())
        out.append(cleaned)
    return "\n".join(out).strip()


def _persist_turn(db: Any, session_id: str, worker_id: str, role: str, content: str) -> None:
    """Guarda un turno en api_conversation."""
    _ensure_api_conversation_table(db)
    sid, wid, r = _safe_sql(session_id), _safe_sql(worker_id), _safe_sql(role)
    esc = (content or "").replace("'", "''")[:16384]
    db.execute(
        f"INSERT INTO api_conversation (session_id, worker_id, role, content) "
        f"VALUES ('{sid}', '{wid}', '{r}', '{esc}')"
    )


def _get_history(db: Any, session_id: str, worker_id: str, limit: int = 6) -> list[dict]:
    """Recupera historial truncado a K turnos (últimos limit*2 mensajes: user+assistant)."""
    _ensure_api_conversation_table(db)
    sid, wid = _safe_sql(session_id), _safe_sql(worker_id)
    try:
        r = db.query(
            f"SELECT role, content FROM api_conversation "
            f"WHERE session_id = '{sid}' AND worker_id = '{wid}' "
            f"ORDER BY created_at DESC LIMIT {limit * 2}"
        )
        rows = json.loads(r) if isinstance(r, str) else (r or [])
        out = []
        for row in reversed(rows or []):
            role = (row.get("role") or "user").lower()
            content = (row.get("content") or "").strip()
            if content:
                out.append({"role": role, "content": content})
        return out[-(limit * 2):]
    except Exception:
        return []


class ChatRequest(BaseModel):
    """Payload para POST /agent/{worker_id}/chat."""
    message: str = Field(..., description="Mensaje del usuario")
    session_id: str = Field("default", description="ID de sesión para historial")
    history: list[dict] = Field(default_factory=list, description="Historial opcional [{role, content}]")
    stream: bool = Field(True, description="Si es True, retorna SSE. Si es False, retorna JSON.")

    model_config = {"extra": "allow"}


@router.post("/{worker_id}/chat", summary="Chat con agente (streaming SSE o JSON)")
async def chat_with_agent(worker_id: str, payload: ChatRequest):
    """
    Envía un mensaje al agente. Retorna StreamingResponse (SSE) token por token o JSON.
    Persiste en api_conversation para historial.
    """
    try:
        graph = _get_or_build_worker_graph(worker_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Error inicializando worker: {exc}")

    db = _get_db()
    session_id = payload.session_id or "default"
    history = payload.history or _get_history(db, session_id, worker_id, limit=6)

    if not payload.stream:
        # Modo JSON directo para n8n / webhooks
        try:
            # Procesar comandos on-the-fly primero
            from duckclaw.agents.on_the_fly_commands import handle_command
            cmd_reply = handle_command(db, session_id, payload.message)
            if cmd_reply:
                return {"response": cmd_reply, "session_id": session_id}

            extra_meta = payload.model_dump(exclude={"message", "session_id", "history", "stream"})
            reply = await _ainvoke(graph, payload.message, history, session_id, metadata=extra_meta)
            reply = _sanitize_for_telegram(reply)
            _persist_turn(db, session_id, worker_id, "user", payload.message)
            _persist_turn(db, session_id, worker_id, "assistant", reply)
            return {"response": reply, "session_id": session_id}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Procesar comandos on-the-fly primero
            from duckclaw.agents.on_the_fly_commands import handle_command
            cmd_reply = handle_command(db, session_id, payload.message)
            if cmd_reply:
                for word in cmd_reply.split(" "):
                    yield f"data: {word} \n\n"
                    await asyncio.sleep(0.02)
                yield "data: [DONE]\n\n"
                return

            extra_meta = payload.model_dump(exclude={"message", "session_id", "history", "stream"})
            reply = await _ainvoke(graph, payload.message, history, session_id, metadata=extra_meta)
            reply = _sanitize_for_telegram(reply)
            _persist_turn(db, session_id, worker_id, "user", payload.message)
            _persist_turn(db, session_id, worker_id, "assistant", reply)
            for word in reply.split(" "):
                yield f"data: {word} \n\n"
                await asyncio.sleep(0.02)
            yield "data: [DONE]\n\n"
        except Exception as exc:
            yield f"data: [ERROR] {exc}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/{worker_id}/history", summary="Historial de chat (K=6)")
async def get_history(worker_id: str, session_id: str, limit: int = 6):
    """
    Recupera el historial de chat truncado a K turnos.
    session_id es requerido.
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id es requerido")
    db = _get_db()
    history = _get_history(db, session_id, worker_id, limit=min(limit, 20))
    return {"worker_id": worker_id, "session_id": session_id, "history": history}

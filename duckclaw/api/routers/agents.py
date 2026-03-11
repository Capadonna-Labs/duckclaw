"""Módulo de agentes: chat con streaming y historial."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re

_chat_log = logging.getLogger(__name__)
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])
tenant_router = APIRouter(prefix="/api/v1/t", tags=["agent-tenant"])

# Cache de grafos por worker_id (evitar rebuild en cada request)


@router.get("/workers", summary="Lista de workers virtuales disponibles")
async def list_workers():
    """Retorna los worker_id disponibles en templates/workers/."""
    from duckclaw.workers.factory import list_workers as _list_workers
    return {"workers": _list_workers()}


@router.get("/llm-config", summary="Estado del LLM (debug)")
async def llm_config():
    """Retorna el proveedor configurado (sin exponer secrets)."""
    provider = os.environ.get("DUCKCLAW_LLM_PROVIDER", "").strip()
    has_key = bool(
        (provider == "deepseek" and os.environ.get("DEEPSEEK_API_KEY"))
        or (provider == "openai" and os.environ.get("OPENAI_API_KEY"))
        or (provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"))
        or (provider in ("ollama", "mlx") and provider)
    )
    return {"llm_provider": provider or "none", "configured": bool(provider and (has_key or provider in ("ollama", "mlx")))}


@router.post("/clear-cache", summary="Limpia caché de grafos (forzar rebuild con LLM actual)")
async def clear_graph_cache():
    """Invalida la caché de workers para que se reconstruyan con la config actual del LLM."""
    _graph_cache.clear()
    return {"ok": True, "message": "Cache cleared. Next request will rebuild graphs."}


_graph_cache: dict[str, Any] = {}


def _get_db() -> Any:
    """DuckDB para api_conversation y workers."""
    from duckclaw import DuckClaw
    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return DuckClaw(db_path)


def _ensure_api_conversation_table(db: Any) -> None:
    """Crea tabla api_conversation si no existe. author_type: AI|HUMAN (Habeas Data)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS api_conversation (
            session_id VARCHAR NOT NULL,
            worker_id VARCHAR NOT NULL,
            role VARCHAR NOT NULL,
            content TEXT,
            author_type VARCHAR DEFAULT 'AI',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        r = db.query(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='api_conversation' AND column_name='author_type' LIMIT 1"
        )
        rows = json.loads(r) if isinstance(r, str) else (r or [])
        if not rows:
            db.execute("ALTER TABLE api_conversation ADD COLUMN author_type VARCHAR DEFAULT 'AI'")
    except Exception:
        pass


def _get_db_path() -> str:
    """Ruta a la DB del gateway (api_conversation + workers)."""
    from duckclaw.gateway_db import get_gateway_db_path
    return get_gateway_db_path()


def _get_llm_config_for_session(db: Any, session_id: str) -> tuple[str, str, str]:
    """Obtiene (provider, model, base_url) para la sesión: agent_config primero, luego env."""
    from duckclaw.agents.on_the_fly_commands import get_chat_state, _get_global_config
    p = get_chat_state(db, session_id, "llm_provider") or _get_global_config(db, "llm_provider")
    m = get_chat_state(db, session_id, "llm_model") or _get_global_config(db, "llm_model")
    u = get_chat_state(db, session_id, "llm_base_url") or _get_global_config(db, "llm_base_url")
    provider = (p or os.environ.get("DUCKCLAW_LLM_PROVIDER", "")).strip()
    model = (m or os.environ.get("DUCKCLAW_LLM_MODEL", "")).strip()
    base_url = (u or os.environ.get("DUCKCLAW_LLM_BASE_URL", "")).strip()
    return provider, model, base_url


def _get_or_build_worker_graph(worker_id: str, session_id: Optional[str] = None) -> Any:
    """Construye o recupera el grafo del worker desde cache. Soporta llm por sesión (/model)."""
    db = _get_db()
    provider, model, base_url = _get_llm_config_for_session(db, session_id or "default")
    cache_key = (worker_id, provider, model, base_url)
    if cache_key in _graph_cache:
        return _graph_cache[cache_key]
    from duckclaw.forge import AgentAssembler, WORKERS_TEMPLATES_DIR
    from duckclaw.integrations.llm_providers import build_llm
    import logging
    manifest_path = WORKERS_TEMPLATES_DIR / worker_id / "manifest.yaml"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' no encontrado")
    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    llm = None
    if provider and provider != "none_llm":
        try:
            llm = build_llm(provider, model, base_url)
        except Exception as e:
            logging.getLogger(__name__).warning("build_llm failed for %s: %s", provider, e)

    # instance_name=None para que todos los workers usen la misma .duckdb (gateway)
    graph = AgentAssembler.from_yaml(manifest_path).build(
        db=None,
        llm=llm,
        db_path=db_path,
        instance_name=None,
        llm_provider=provider if provider else None,
        llm_model=model if model else None,
        llm_base_url=base_url if base_url else None,
    )
    _graph_cache[cache_key] = graph
    return graph


async def _ainvoke(
    graph: Any, message: str, history: list, chat_id: str, metadata: Optional[dict[Any, Any]] = None
) -> str:
    """Invocación async del grafo (compatible con graph_server)."""
    # Inyectar thread_id para handoff_trigger (HITL)
    try:
        from duckclaw.activity.handoff_context import set_handoff_thread_id
        set_handoff_thread_id(chat_id)
    except ImportError:
        pass
    # "input" va primero para que LangSmith muestre el mensaje del usuario en la columna Input
    # Incluir messages para grafos que filtran por input_schema; incoming en varios canales por compatibilidad
    from langchain_core.messages import HumanMessage
    state = {
        "input": message,
        "incoming": message,
        "messages": [HumanMessage(content=message)],
        "history": history or [],
        "chat_id": chat_id,
    }
    loop = asyncio.get_event_loop()
    
    metadata = metadata or {}
    channel = metadata.get("channel", "Api")
    username = metadata.get("username", "Unknown")
    
    clean_username = "".join(c if c.isalnum() else "_" for c in str(username))
    run_name_prefix = f"{str(channel).capitalize()}_{clean_username}_{chat_id}"
    
    full_metadata = {"session_id": chat_id, "thread_id": chat_id}
    full_metadata.update(metadata)

    run_name = "DuckClaw"
    try:
        spec = getattr(graph, "_worker_spec", None)
        if spec:
            run_name = getattr(spec, "name", run_name) or run_name
    except Exception:
        pass
    full_metadata["incoming"] = message
    config = {
        "configurable": {"thread_id": chat_id, "incoming": message},
        "metadata": full_metadata,
        "run_name": run_name,
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


def _normalize_reply_for_user(text: str) -> str:
    """Normaliza respuestas crudas (schema dumps, NULL) antes de enviar al usuario."""
    from duckclaw.utils import normalize_reply_for_user
    return normalize_reply_for_user(text)


def _sanitize_for_telegram(text: str) -> str:
    """
    Limpia la salida para que Telegram Markdown (parse_mode='Markdown') la interprete bien.
    - Quita ## ### #### y líneas ---
    - Escapa _ * ` [ que rompen el parser cuando no forman entidades válidas
    """
    if not text or not isinstance(text, str):
        return text
    lines = text.split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped in ("---", "***", "___"):
            continue
        cleaned = re.sub(r"^#+\s*", "", line.lstrip())
        # Escapar para Telegram MarkdownV1: _ * ` [ (evita "can't parse entities")
        cleaned = cleaned.replace("\\", "\\\\")
        cleaned = cleaned.replace("_", "\\_")
        cleaned = cleaned.replace("*", "\\*")
        cleaned = cleaned.replace("`", "\\`")
        cleaned = cleaned.replace("[", "\\[")
        out.append(cleaned)
    return "\n".join(out).strip()


def _persist_turn(
    db: Any, session_id: str, worker_id: str, role: str, content: str, author_type: str = "AI"
) -> None:
    """Guarda un turno en api_conversation. author_type: AI|HUMAN (Habeas Data)."""
    _ensure_api_conversation_table(db)
    sid, wid, r = _safe_sql(session_id), _safe_sql(worker_id), _safe_sql(role)
    at = _safe_sql(author_type)[:16]
    esc = (content or "").replace("'", "''")[:16384]
    db.execute(
        f"INSERT INTO api_conversation (session_id, worker_id, role, content, author_type) "
        f"VALUES ('{sid}', '{wid}', '{r}', '{esc}', '{at}')"
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


async def _enqueue_graph_lead_profiler(
    worker_id: str, session_id: str, message: str, history: list, reply: str
) -> None:
    """Encola GraphLeadProfiler en ARQ (fire-and-forget). Spec: Sovereign CRM."""
    try:
        from arq import create_pool
        from duckclaw.forge import AgentAssembler, WORKERS_TEMPLATES_DIR

        manifest_path = WORKERS_TEMPLATES_DIR / worker_id / "manifest.yaml"
        if not manifest_path.is_file():
            return
        import yaml
        data = yaml.safe_load(manifest_path.read_text()) or {}
        crm = data.get("crm") or {}
        if not (crm.get("enabled") if isinstance(crm, dict) else crm):
            return
        from arq.connections import RedisSettings
        redis_url = os.environ.get("REDIS_URL") or os.environ.get("ARQ_REDIS_URL", "redis://localhost:6379")
        parts = redis_url.replace("redis://", "").split("/")[0].split(":")
        settings = RedisSettings(host=parts[0], port=int(parts[1]) if len(parts) > 1 else 6379)
        pool = await create_pool(settings)
        await pool.enqueue_job(
            "graph_lead_profiler_job",
            worker_id,
            session_id,
            message,
            history or [],
            reply,
        )
        await pool.close()
    except Exception:
        pass


def _get_session_status(session_id: str) -> str:
    """Estado de sesión (HITL). Retorna IDLE si Redis no disponible."""
    try:
        from duckclaw.activity.session_state import SessionStateManager, STATE_MANUAL_MODE
        mgr = SessionStateManager()
        return mgr.get_status(session_id)
    except Exception:
        return "IDLE"


def _get_default_worker() -> str:
    """Worker por defecto cuando no hay /role previo. Env: DUCKCLAW_DEFAULT_WORKER."""
    return os.environ.get("DUCKCLAW_DEFAULT_WORKER", "finanz").strip() or "finanz"


@router.post("/chat", summary="Chat con DuckClaw (worker dinámico vía /role)")
async def chat_with_agent_dynamic(payload: ChatRequest):
    """
    Endpoint genérico para n8n/Telegram. El worker se determina por agent_config (/role).
    Si no hay /role previo, usa DUCKCLAW_DEFAULT_WORKER (default: finanz).
    Usa este endpoint en lugar de /agent/finanz/chat para soportar /role.
    """
    session_id = payload.session_id or "default"
    db = _get_db()
    from duckclaw.agents.on_the_fly_commands import get_worker_id_for_chat
    worker_id = (get_worker_id_for_chat(db, session_id) or "").strip() or _get_default_worker()
    return await chat_with_agent(worker_id, payload)


@router.post("/{worker_id}/chat", summary="Chat con agente (streaming SSE o JSON)")
async def chat_with_agent(worker_id: str, payload: ChatRequest):
    """
    Envía un mensaje al agente. Retorna StreamingResponse (SSE) token por token o JSON.
    Si MANUAL_MODE (HITL), rechaza y retorna status=ignored.
    Respeta /role: si el chat tiene worker_id en agent_config (por /role previo), usa ese.
    """
    session_id = payload.session_id or "default"
    status = _get_session_status(session_id)
    if status == "MANUAL_MODE":
        return {"status": "ignored", "reason": "manual_mode_active", "session_id": session_id}

    db = _get_db()
    # Respetar worker_id de /role (agent_config) para Telegram/n8n; si no hay override, usar el de la URL
    from duckclaw.agents.on_the_fly_commands import get_worker_id_for_chat
    effective_worker_id = (get_worker_id_for_chat(db, session_id) or "").strip() or worker_id

    try:
        graph = _get_or_build_worker_graph(effective_worker_id, session_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Error inicializando worker: {exc}")

    history = payload.history or _get_history(db, session_id, effective_worker_id, limit=6)

    if not payload.stream:
        # Modo JSON directo para n8n / webhooks
        try:
            # Procesar comandos on-the-fly primero
            from duckclaw.agents.on_the_fly_commands import handle_command
            cmd_reply = handle_command(db, session_id, payload.message)
            if cmd_reply:
                cmd_reply = _sanitize_for_telegram(cmd_reply)
                _chat_log.info("[chat] IN=%r | OUT=%r", (payload.message or "")[:120], (cmd_reply or "")[:120])
                return {"response": cmd_reply, "session_id": session_id}

            _chat_log.info("[chat] IN=%r", (payload.message or "")[:200])
            extra_meta = payload.model_dump(exclude={"message", "session_id", "history", "stream"})
            reply = await _ainvoke(graph, payload.message, history, session_id, metadata=extra_meta)
            reply = _normalize_reply_for_user(reply)
            reply = _sanitize_for_telegram(reply)
            _chat_log.info("[chat] OUT=%r", (reply or "")[:200])
            _persist_turn(db, session_id, effective_worker_id, "user", payload.message)
            _persist_turn(db, session_id, effective_worker_id, "assistant", reply)
            asyncio.create_task(_enqueue_graph_lead_profiler(
                effective_worker_id, session_id, payload.message, history, reply
            ))
            return {"response": reply or "Sin respuesta.", "session_id": session_id}
        except HTTPException:
            raise
        except Exception as exc:
            # Para n8n: siempre retornar JSON con "response" para que Responder Telegram no falle
            import logging
            import traceback
            _log = logging.getLogger(__name__)
            _log.warning("chat error: %s\n%s", exc, traceback.format_exc())
            return {
                "response": "Lo siento, hubo un error al procesar. Intenta de nuevo.",
                "session_id": session_id,
            }

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Procesar comandos on-the-fly primero
            from duckclaw.agents.on_the_fly_commands import handle_command
            cmd_reply = handle_command(db, session_id, payload.message)
            if cmd_reply:
                cmd_reply = _sanitize_for_telegram(cmd_reply)
                _chat_log.info("[chat] IN=%r | OUT=%r", (payload.message or "")[:120], (cmd_reply or "")[:120])
                for word in cmd_reply.split(" "):
                    yield f"data: {word} \n\n"
                    await asyncio.sleep(0.02)
                yield "data: [DONE]\n\n"
                return

            _chat_log.info("[chat] IN=%r", (payload.message or "")[:200])
            extra_meta = payload.model_dump(exclude={"message", "session_id", "history", "stream"})
            reply = await _ainvoke(graph, payload.message, history, session_id, metadata=extra_meta)
            reply = _normalize_reply_for_user(reply)
            reply = _sanitize_for_telegram(reply)
            _chat_log.info("[chat] OUT=%r", (reply or "")[:200])
            _persist_turn(db, session_id, effective_worker_id, "user", payload.message)
            _persist_turn(db, session_id, effective_worker_id, "assistant", reply)
            asyncio.create_task(_enqueue_graph_lead_profiler(
                effective_worker_id, session_id, payload.message, history, reply
            ))
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


@router.delete("/{worker_id}/history", summary="Borrar historial (Limpiar / /forget)")
async def delete_history(worker_id: str, session_id: str):
    """Borra el historial de la sesión para este worker. Usado por botón Limpiar."""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id es requerido")
    db = _get_db()
    _ensure_api_conversation_table(db)
    sid, wid = _safe_sql(session_id), _safe_sql(worker_id)
    db.execute(
        f"DELETE FROM api_conversation WHERE session_id = '{sid}' AND worker_id = '{wid}'"
    )
    return {"ok": True, "message": "Historial borrado"}


# --- Tenant routes: /api/v1/t/{tenant_id}/agent/... (delegan a handlers legacy) ---


@tenant_router.post("/{tenant_id}/agent/{worker_id}/chat", summary="Chat con agente (tenant)")
async def chat_with_agent_tenant(tenant_id: str, worker_id: str, payload: ChatRequest, request: Request):
    """Mismo handler que chat legacy; tenant_id en request.state para audit y namespacing futuro."""
    request.state.tenant_id = tenant_id
    return await chat_with_agent(worker_id, payload)


@tenant_router.get("/{tenant_id}/agent/{worker_id}/history", summary="Historial de chat (tenant)")
async def get_history_tenant(tenant_id: str, worker_id: str, session_id: str, request: Request, limit: int = 6):
    """Mismo handler que history legacy; tenant_id en request.state."""
    request.state.tenant_id = tenant_id
    return await get_history(worker_id, session_id, limit)


@tenant_router.delete("/{tenant_id}/agent/{worker_id}/history", summary="Borrar historial (tenant)")
async def delete_history_tenant(tenant_id: str, worker_id: str, session_id: str, request: Request):
    """Mismo handler que delete_history legacy; tenant_id en request.state."""
    request.state.tenant_id = tenant_id
    return await delete_history(worker_id, session_id)

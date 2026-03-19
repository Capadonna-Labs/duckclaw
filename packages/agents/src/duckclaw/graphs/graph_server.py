"""
DuckClaw LangGraph API Server
─────────────────────────────
Expone el grafo LangGraph como una API REST para uso desde LangSmith,
aplicaciones externas o integración en internet.

Uso directo:
  python -m duckclaw.graphs.graph_server               # puerto 8123
  python -m duckclaw.graphs.graph_server --port 9000
  python -m duckclaw.graphs.graph_server --host 0.0.0.0 --port 8123

Via duckops:
  duckops serve --port 8123
  duckops serve --pm2 --name DuckClaw-API

Endpoints:
  GET  /             → info del grafo y configuración activa
  GET  /health       → {"status": "ok", "model": "mlx:Slayer-8B-V1.1"}
  POST /invoke       → invocar el grafo con un mensaje
  POST /stream       → invocar con streaming SSE (requiere Accept: text/event-stream)
  GET  /graph        → JSON del grafo compilado (para LangSmith Studio)
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

# ── dotenv ─────────────────────────────────────────────────────────────────────

def _load_dotenv() -> None:
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent.parent):
        env_file = base / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    if key:
                        os.environ.setdefault(key, value)
            except Exception:
                pass
            break

_load_dotenv()

# ── FastAPI app ────────────────────────────────────────────────────────────────

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse
    from pydantic import BaseModel, Field
except ImportError as exc:
    raise ImportError(
        "Instala las dependencias del servidor:\n"
        "  uv sync --extra serve\n"
        "  # o: pip install fastapi uvicorn"
    ) from exc

app = FastAPI(
    title="DuckClaw LangGraph API",
    description="API REST para el grafo LangGraph de DuckClaw con trazas a LangSmith.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _tailscale_auth_middleware(request: Request, call_next):
    """Valida X-Tailscale-Auth-Key si DUCKCLAW_TAILSCALE_AUTH_KEY está definida."""
    from starlette.responses import JSONResponse
    auth_key = os.environ.get("DUCKCLAW_TAILSCALE_AUTH_KEY", "").strip()
    if not auth_key:
        return await call_next(request)
    path = request.url.path.rstrip("/") or "/"
    if path in ("/", "/health"):
        return await call_next(request)
    header_key = request.headers.get("X-Tailscale-Auth-Key", "").strip()
    if header_key != auth_key:
        return JSONResponse(
            status_code=401,
            content={"detail": "X-Tailscale-Auth-Key inválida o faltante"},
        )
    return await call_next(request)


app.middleware("http")(_tailscale_auth_middleware)

# ── Estado global del grafo ────────────────────────────────────────────────────

_graph_state: dict[str, Any] = {}
_graph_init_error: Optional[Exception] = None


def _get_or_build_graph() -> Any:
    """Build/cache the compiled LangGraph via AgentAssembler. Safe to call from sync context."""
    if _graph_state.get("graph") is not None:
        return _graph_state["graph"]

    from duckclaw import DuckClaw
    from duckclaw.integrations.llm_providers import build_llm
    from duckclaw.forge import AgentAssembler, MANAGER_ROUTER_YAML

    from duckclaw.gateway_db import get_gateway_db_path
    db_path = get_gateway_db_path()

    import os as _os
    _os.makedirs(str(Path(db_path).parent), exist_ok=True)

    provider = os.environ.get("DUCKCLAW_LLM_PROVIDER", "mlx").strip().lower()
    model    = os.environ.get("DUCKCLAW_LLM_MODEL", "").strip()
    base_url = os.environ.get("DUCKCLAW_LLM_BASE_URL", "http://127.0.0.1:8080/v1").strip()
    system_prompt = os.environ.get("DUCKCLAW_SYSTEM_PROMPT", "Eres un asistente útil con acceso a una base de datos.").strip()

    db  = DuckClaw(db_path)

    # Telegram Guard (Telegram Guard / Whitelist): asegurar esquema persistente.
    # Hacemos esto aquí para que funcione incluso cuando el pre-init de FastAPI
    # o lifespan no llegue (y para usar la misma conexión DuckDB).
    try:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS main.authorized_users (
                tenant_id VARCHAR,
                user_id VARCHAR,
                username VARCHAR,
                role VARCHAR DEFAULT 'user',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, user_id)
            )
            """
        )
    except Exception as exc:
        # No romper el server: si falla por lock/permiso, el guard bloqueará todo,
        # y el problema se verá en logs/observabilidad.
        print(f"[telegram_guard] Could not ensure authorized_users table: {exc}", flush=True)

    llm = build_llm(provider, model, base_url)
    if llm is None:
        raise RuntimeError(
            "No se pudo inicializar el LLM. "
            "Configura DUCKCLAW_LLM_PROVIDER y DUCKCLAW_LLM_BASE_URL en .env."
        )

    # Grafo manager: orquestador que asigna tareas a subagentes (workers); state incluye chat_id
    graph = AgentAssembler.from_yaml(MANAGER_ROUTER_YAML).build(
        db=db,
        llm=llm,
        system_prompt=system_prompt,
        llm_provider=provider,
        llm_model=model,
        llm_base_url=base_url,
        db_path=db_path,
    )

    _graph_state["graph"]    = graph
    _graph_state["db"]       = db
    _graph_state["provider"] = provider
    _graph_state["model"]    = model
    _graph_state["base_url"] = base_url
    _graph_state["db_path"]  = db_path
    return graph


# ── Pre-inicialización en tiempo de importación ────────────────────────────────
# langgraph dev importa este módulo antes de arrancar el event loop (contexto sync).
# Inicializando aquí, get_graph() devuelve el grafo cacheado sin hacer ningún I/O,
# evitando el BlockingError de blockbuster al ser llamado desde contexto async.

def _pre_init() -> None:
    global _graph_init_error
    try:
        _get_or_build_graph()
    except Exception as exc:
        _graph_init_error = exc
        print(f"[graph_server] Pre-init warning: {exc}", flush=True)

_pre_init()


def _resolve_display_model() -> str:
    provider = os.environ.get("DUCKCLAW_LLM_PROVIDER", "mlx")
    if provider == "mlx":
        mid = (os.environ.get("MLX_MODEL_ID") or os.environ.get("MLX_MODEL_PATH") or "").strip()
        if mid:
            return f"mlx:{mid.rstrip('/').rsplit('/', 1)[-1]}"
        return "mlx:local"
    model = os.environ.get("DUCKCLAW_LLM_MODEL", "")
    return f"{provider}:{model}" if model else provider


# ── Pydantic models ────────────────────────────────────────────────────────────

class InvokeRequest(BaseModel):
    message: str = Field(..., description="Mensaje del usuario")
    chat_id: str = Field("api", description="ID de sesión (para memoria de conversación)")
    tenant_id: str = Field("default", description="ID del tenant (para whitelist y aislamiento de workers)")
    history: list[dict] = Field(default_factory=list, description="Historial [{role, content}]")
    stream: bool = Field(False, description="Si true, usar /stream en su lugar")
    username: str | None = Field(None, description="Nombre del usuario (para grupos)")
    chat_type: str | None = Field(None, description="Tipo de chat: private, group, supergroup, etc.")
    user_id: str | None = Field(None, description="ID del usuario para resolver bóveda activa")


class InvokeResponse(BaseModel):
    reply: str
    model: str
    elapsed_ms: int
    chat_id: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/", summary="Info del servidor")
async def root():
    return {
        "service":    "DuckClaw LangGraph API",
        "version":    "0.1.0",
        "model":      _resolve_display_model(),
        "db_path":    os.environ.get("DUCKCLAW_DB_PATH", "(default)"),
        "tracing":    os.environ.get("LANGCHAIN_TRACING_V2", "false"),
        "project":    os.environ.get("LANGCHAIN_PROJECT", ""),
        "endpoints":  ["/invoke", "/stream", "/health", "/docs"],
    }


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok", "model": _resolve_display_model()}


@app.post("/invoke", response_model=InvokeResponse, summary="Invocar el grafo")
async def invoke(req: InvokeRequest):
    """
    Envía un mensaje al grafo LangGraph y retorna la respuesta.
    Las trazas se envían automáticamente a LangSmith si LANGCHAIN_TRACING_V2=true.
    """
    try:
        graph = _get_or_build_graph()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Error inicializando el grafo: {exc}")

    # Enriquecer el estado con identidad (username/chat_type) para general_graph.
    history = req.history or []
    state = {
        "incoming": req.message,
        "history": history,
        "username": req.username or "",
        "chat_type": (req.chat_type or "").lower() if req.chat_type else "",
    }

    t0 = time.monotonic()
    try:
        # El grafo manager se encarga de mapear state → subgrafos; general_graph usará username/chat_type.
        result = await _ainvoke(
            graph,
            state["incoming"],
            history,
            req.chat_id,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error en el grafo: {exc}")

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return InvokeResponse(
        reply=result.get("reply", ""),
        model=_resolve_display_model(),
        elapsed_ms=elapsed_ms,
        chat_id=req.chat_id,
    )


@app.post("/stream", summary="Invocar el grafo con streaming SSE")
async def stream(req: InvokeRequest):
    """
    Streaming de la respuesta token por token usando Server-Sent Events (SSE).
    Cada evento tiene el formato: data: <token>\\n\\n
    El evento final es: data: [DONE]\\n\\n
    """
    try:
        graph = _get_or_build_graph()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Error inicializando el grafo: {exc}")

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            invoke_result = await _ainvoke(
                graph,
                req.message,
                req.history,
                req.chat_id,
                tenant_id=req.tenant_id,
                user_id=req.user_id,
            )
            reply = invoke_result.get("reply", "") or ""
            for word in reply.split(" "):
                yield f"data: {word} \n\n"
                await _async_sleep(0.02)
            yield "data: [DONE]\n\n"
        except Exception as exc:
            yield f"data: [ERROR] {exc}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/graph", summary="Estructura del grafo compilado")
async def graph_info():
    """Retorna la estructura del grafo en formato JSON (compatible con LangSmith Studio)."""
    try:
        graph = _get_or_build_graph()
        # LangGraph compiled graphs exponen get_graph()
        if hasattr(graph, "get_graph"):
            g = graph.get_graph()
            return JSONResponse(content={
                "nodes": [str(n) for n in (g.nodes if hasattr(g, "nodes") else [])],
                "edges": [str(e) for e in (g.edges if hasattr(g, "edges") else [])],
            })
        return {"graph": "compiled", "type": str(type(graph).__name__)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Helpers async ──────────────────────────────────────────────────────────────

async def _ainvoke(
    graph: Any,
    message: str,
    history: list,
    chat_id: str,
    *,
    tenant_id: str = "default",
    user_id: str | None = None,
    vault_db_path: str | None = None,
    is_system_prompt: bool | None = False,
) -> dict:
    """
    Invoca el grafo y retorna {"reply": str, "messages": list | None}.
    messages (cuando existe) es la secuencia completa del turno para trazas SFT (tool_calls, tool, assistant).
    """
    import asyncio

    state = {
        "incoming": message,
        "history": history or [],
        "chat_id": chat_id,
        "tenant_id": tenant_id,
        "user_id": (user_id or "").strip() or str(chat_id),
        "vault_db_path": (vault_db_path or "").strip() or "",
    }
    if is_system_prompt:
        state["is_system_prompt"] = True
    loop = asyncio.get_event_loop()

    if hasattr(graph, "ainvoke"):
        result = await graph.ainvoke(state)
    else:
        result = await loop.run_in_executor(None, graph.invoke, state)

    reply = str(result.get("reply") or result.get("output") or "Sin respuesta.")
    return {"reply": reply, "messages": result.get("messages")}


async def _async_sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)


# ── get_graph() para langgraph.json / LangSmith Studio ─────────────────────────

def get_graph() -> Any:
    """
    Entry point para langgraph dev / LangSmith Studio.
    El grafo ya está pre-inicializado en tiempo de importación — no hace I/O.
    """
    if _graph_state.get("graph") is None:
        if _graph_init_error is not None:
            raise _graph_init_error
        _get_or_build_graph()
    return _graph_state["graph"]


def get_db() -> Any:
    """Devuelve la instancia DuckClaw del grafo (para fly commands en el Gateway)."""
    if _graph_state.get("db") is None:
        if _graph_init_error is not None:
            raise _graph_init_error
        _get_or_build_graph()
    return _graph_state.get("db")


# ── __main__ ───────────────────────────────────────────────────────────────────

def _run_server(host: str = "0.0.0.0", port: int = 8123, reload: bool = False) -> None:
    import uvicorn
    print(f"🦆⚔️  DuckClaw LangGraph API → http://{host}:{port}", flush=True)
    print(f"   Docs  → http://{host}:{port}/docs", flush=True)
    print(f"   Model → {_resolve_display_model()}", flush=True)
    tracing = os.environ.get("LANGCHAIN_TRACING_V2", "false")
    project = os.environ.get("LANGCHAIN_PROJECT", "")
    if tracing == "true" and project:
        print(f"   LangSmith → project={project} (trazas activas)", flush=True)
    elif tracing != "true":
        print("   LangSmith → trazas DESACTIVADAS (añade LANGCHAIN_TRACING_V2=true a .env)", flush=True)
    uvicorn.run(
        "duckclaw.graphs.graph_server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    import argparse
    try:
        default_port = int(os.environ.get("DUCKCLAW_API_PORT", "8123"))
    except ValueError:
        default_port = 8123
    parser = argparse.ArgumentParser(description="DuckClaw LangGraph API Server")
    parser.add_argument("--host",   default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--port",   default=default_port, type=int, help=f"Puerto (default: {default_port}, o DUCKCLAW_API_PORT)")
    parser.add_argument("--reload", action="store_true",    help="Reload automático en desarrollo")
    args = parser.parse_args()
    _run_server(host=args.host, port=args.port, reload=args.reload)

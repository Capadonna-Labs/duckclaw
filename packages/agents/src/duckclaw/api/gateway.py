"""
DuckClaw API Gateway — FastAPI app para n8n, Angular, Telegram.

Endpoints: /api/v1/agent/chat, /api/v1/homeostasis/status, /api/v1/system/health.
Usa duckclaw.agents.graph_server para la lógica del grafo.
"""

from __future__ import annotations

import logging
import os
import shutil
import traceback
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

# Cargar .env (cwd, package dir, repo root)
_repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
for _base in (Path.cwd(), Path(__file__).resolve().parent.parent.parent.parent, _repo_root):
    if not _base:
        continue
    _env = _base / ".env"
    if _env.is_file():
        for _line in _env.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                if _k.strip():
                    os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))
        break

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Asegurar que los logs in/out/tool_use aparezcan en PM2 (stdout)
import sys
def _ensure_duckclaw_log_handler():
    """Añade handler a duckclaw.* para que in/out/tool_use aparezcan en PM2."""
    for name in ("duckclaw.api.gateway", "duckclaw.agents.general_graph", "duckclaw.agents.retail_graph", "duckclaw.bi.agent"):
        log = logging.getLogger(name)
        if not log.handlers:
            h = logging.StreamHandler(sys.stdout)
            h.setLevel(logging.INFO)
            h.setFormatter(logging.Formatter("%(message)s"))
            log.addHandler(h)
            log.setLevel(logging.INFO)
_ensure_duckclaw_log_handler()
_gateway_log = logging.getLogger("duckclaw.api.gateway")

app = FastAPI(
    title="DuckClaw API Gateway",
    description="API para n8n, Angular, Telegram. Agentes, homeostasis, system health.",
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


# ── Root y health ─────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": "DuckClaw API Gateway",
        "version": "0.1.0",
        "endpoints": [
            "/api/v1/agent/chat",
            "/api/v1/agent/{worker_id}/chat",
            "/api/v1/agent/workers",
            "/api/v1/agent/{worker_id}/history",
            "/api/v1/homeostasis/status",
            "/api/v1/homeostasis/ask_task",
            "/api/v1/system/health",
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── System health ────────────────────────────────────────────────────────────

@app.get("/api/v1/system/health")
async def system_health():
    tailscale = "unknown"
    if shutil.which("tailscale"):
        try:
            r = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            tailscale = "ok" if r.returncode == 0 else "error"
        except Exception:
            tailscale = "error"
    duckdb = "ok"
    mlx = "n/a"
    provider = (os.environ.get("DUCKCLAW_LLM_PROVIDER") or "").strip().lower()
    if provider == "mlx":
        mlx = "ok"  # Asumir MLX si está configurado
    return {"tailscale": tailscale, "duckdb": duckdb, "mlx": mlx}


# ── Homeostasis ───────────────────────────────────────────────────────────────

@app.get("/api/v1/homeostasis/status")
async def homeostasis_status():
    return []


class AskTaskBody(BaseModel):
    suggested_objectives: list[str] = Field(default_factory=list)


@app.post("/api/v1/homeostasis/ask_task")
async def homeostasis_ask_task(body: AskTaskBody = None):
    return {"ok": True, "trigger": "timer"}


# ── Agent ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/agent/workers")
async def agent_workers():
    try:
        from duckclaw.workers.factory import list_workers
        workers = list_workers()
        return {"workers": workers}
    except Exception as e:
        return {"workers": ["finanz"]}  # Fallback


@app.get("/api/v1/agent/{worker_id}/history")
async def agent_history(worker_id: str, session_id: str = "default"):
    return {"history": [], "worker_id": worker_id}


class ChatBody(BaseModel):
    message: str = Field(..., description="Mensaje del usuario")
    session_id: str = Field("default", description="ID de sesión")
    history: list[dict] = Field(default_factory=list)
    stream: bool = Field(False, description="Streaming SSE")


@app.post("/api/v1/agent/chat")
@app.post("/api/v1/agent/{worker_id}/chat")
async def agent_chat(worker_id: Optional[str] = None, body: ChatBody = None):
    if body is None:
        body = ChatBody(message="", session_id="default")
    return await _invoke_chat(body.message, body.session_id, body.history, worker_id or "finanz")


def _truncate_log(s: str, max_len: int = 200) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."

async def _invoke_chat(message: str, session_id: str, history: list, worker_id: str):
    log = _gateway_log
    log.info("in: %s", _truncate_log(message))

    # Fly commands (/role, /skills, /forget, etc.) — ejecutar antes del grafo
    msg_stripped = (message or "").strip()
    if msg_stripped.startswith("/"):
        try:
            from duckclaw.agents.on_the_fly_commands import handle_command
            from duckclaw.agents.graph_server import get_db
            db = get_db()
            cmd_reply = handle_command(db, session_id, message)
            if cmd_reply is not None:
                log.info("fly: %s", _truncate_log(cmd_reply))
                return {
                    "response": cmd_reply,
                    "session_id": session_id,
                    "worker_id": worker_id,
                    "elapsed_ms": 0,
                }
        except Exception as exc:
            log.error("fly command failed: %s", exc)

    try:
        from duckclaw.agents.graph_server import _get_or_build_graph, _ainvoke
        graph = _get_or_build_graph()
    except Exception as exc:
        _gateway_log.error("graph init failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(status_code=503, detail=f"Error inicializando el grafo: {exc}")

    try:
        from duckclaw.agents.activity import set_busy, set_idle
        set_busy(session_id, task=message)
    except Exception:
        pass
    t0 = time.monotonic()
    try:
        result = await _ainvoke(graph, message, history or [], session_id)
    except Exception as exc:
        try:
            from duckclaw.agents.activity import set_idle
            set_idle(session_id)
        except Exception:
            pass
        try:
            from duckclaw.agents.on_the_fly_commands import append_task_audit, get_worker_id_for_chat
            from duckclaw.agents.graph_server import get_db
            db = get_db()
            wid = get_worker_id_for_chat(db, session_id) or worker_id
            elapsed_fail = int((time.monotonic() - t0) * 1000)
            append_task_audit(db, session_id, wid, message, "FAILED", elapsed_fail)
        except Exception:
            pass
        _gateway_log.error("agent_chat failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        from duckclaw.agents.activity import set_idle
        set_idle(session_id)
    except Exception:
        pass
    _gateway_log.info("out: %s", _truncate_log(result))
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    try:
        from duckclaw.agents.on_the_fly_commands import append_task_audit, get_worker_id_for_chat
        from duckclaw.agents.graph_server import get_db
        db = get_db()
        wid = get_worker_id_for_chat(db, session_id) or worker_id
        append_task_audit(db, session_id, wid, message, "SUCCESS", elapsed_ms)
    except Exception:
        pass
    try:
        from duckclaw.agents.on_the_fly_commands import _telegram_safe
        result = _telegram_safe(result)
    except Exception:
        pass
    return {
        "response": result,
        "session_id": session_id,
        "worker_id": worker_id,
        "elapsed_ms": elapsed_ms,
    }


# ── Quotes router ────────────────────────────────────────────────────────────

from duckclaw.api.routers import quotes
app.include_router(quotes.router)


# ── run_gateway ───────────────────────────────────────────────────────────────

def run_gateway(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    import uvicorn
    uvicorn.run(
        "duckclaw.api.gateway:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )

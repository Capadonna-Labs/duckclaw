# services/api-gateway/main.py
"""
DuckClaw API Gateway — Microservicio unificado.

Punto de entrada único para n8n, Telegram, Angular y escrituras a DuckDB.
Endpoints: /api/v1/agent/chat, /api/v1/db/write, homeostasis, system health.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional
from urllib import request as _url_request
from urllib.error import URLError

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import redis.asyncio as redis

from core.models import ChatRequest
from duckclaw.vaults import ensure_registry as ensure_vault_registry
from duckclaw.vaults import resolve_active_vault, validate_user_db_path

# Cargar .env desde repo root
_repo_root = Path(__file__).resolve().parent.parent.parent
for _base in (_repo_root, Path.cwd()):
    _env = _base / ".env"
    if _env.is_file():
        for _line in _env.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                if _k.strip():
                    os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))
        break

try:
    from core.config import settings
except ImportError:
    class _Settings:
        PROJECT_NAME = "DuckClaw API Gateway"
        VERSION = "0.1.0"
        REDIS_URL = "redis://localhost:6379/0"
    settings = _Settings()

# Logs para PM2
def _ensure_log_handler():
    for name in ("duckclaw.gateway", "duckclaw.graphs.general_graph", "duckclaw.graphs.retail_graph", "duckclaw.graphs.manager_graph", "duckclaw.bi.agent"):
        log = logging.getLogger(name)
        if not log.handlers:
            h = logging.StreamHandler(sys.stdout)
            h.setLevel(logging.INFO)
            h.setFormatter(logging.Formatter("%(message)s"))
            log.addHandler(h)
            log.setLevel(logging.INFO)
_ensure_log_handler()
_gateway_log = logging.getLogger("duckclaw.gateway")

_AUTHORIZED_USERS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS main.authorized_users (
    tenant_id VARCHAR,
    user_id VARCHAR,
    username VARCHAR,
    role VARCHAR DEFAULT 'user',
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, user_id)
);
"""

# ANSI colors (foreground). Kept readable on dark terminals.
_CHAT_COLORS = (
    "\033[38;5;39m",   # blue
    "\033[38;5;45m",   # cyan
    "\033[38;5;82m",   # green
    "\033[38;5;190m",  # yellow
    "\033[38;5;208m",  # orange
    "\033[38;5;201m",  # magenta
    "\033[38;5;135m",  # purple
    "\033[38;5;51m",   # aqua
)
_ANSI_RESET = "\033[0m"


def _chat_color(chat_id: str) -> str:
    cid = (chat_id or "default").encode("utf-8", errors="ignore")
    idx = int(hashlib.sha1(cid).hexdigest(), 16) % len(_CHAT_COLORS)
    return _CHAT_COLORS[idx]


def _c_chat(chat_id: str, text: str) -> str:
    """Colorize text by chat_id for PM2/terminal readability."""
    return f"{_chat_color(chat_id)}{text}{_ANSI_RESET}"


def _c_chat_id(chat_id: str) -> str:
    """Colorize only chat_id value."""
    cid = repr(chat_id)
    return f"{_chat_color(chat_id)}{cid}{_ANSI_RESET}"


def _normalize_local_artifacts_to_db() -> None:
    """Mueve artefactos locales conocidos a `db/` si aparecen en la raíz."""
    try:
        repo_root = Path(__file__).resolve().parent.parent.parent
        db_dir = repo_root / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        for filename in ("SELECT", "dump.rdb"):
            src = repo_root / filename
            dst = db_dir / filename
            if src.exists():
                try:
                    if dst.exists():
                        src.unlink(missing_ok=True)
                    else:
                        src.replace(dst)
                except Exception:
                    pass
    except Exception:
        pass


def _langsmith_auth_log(*, auth_status: str, user_id: str, tenant_id: str) -> None:
    """
    Best-effort audit a LangSmith para Telegram Guard.

    Tags (según spec):
      - `auth_status: authorized`
      - `auth_status: unauthorized_attempt`
    """
    try:
        api_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
        if not api_key:
            return
        if os.environ.get("LANGCHAIN_TRACING_V2", "").lower() not in ("true", "1"):
            return

        from langsmith import Client  # noqa: PLC0415

        client = Client(api_key=api_key)
        tag = f"auth_status: {auth_status}"
        client.create_run(
            name="telegram_guard_auth",
            run_type="chain",
            inputs={"user_id": str(user_id), "tenant_id": str(tenant_id)},
            outputs={"auth_status": auth_status},
            tags=[tag, "telegram_guard"],
        )
    except Exception:
        # Auditoría best-effort: nunca rompas el flujo de seguridad.
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(str(settings.REDIS_URL), decode_responses=True)
    _normalize_local_artifacts_to_db()
    # Forzar que Redis persista dump.rdb dentro de db/ (best-effort).
    try:
        repo_root = Path(__file__).resolve().parent.parent.parent
        redis_dir = str((repo_root / "db").resolve())
        await app.state.redis.config_set("dir", redis_dir)
        await app.state.redis.config_set("dbfilename", "dump.rdb")
    except Exception:
        pass
    # Prepara el esquema de Telegram Guard (idempotente).
    try:
        # Importante: reutilizar la misma conexión DuckDB que mantiene graph_server
        # para evitar conflictos de lock.
        from duckclaw.graphs.graph_server import get_db

        db = get_db()
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS main.authorized_users (
                tenant_id VARCHAR,
                user_id VARCHAR,
                username VARCHAR,
                role VARCHAR DEFAULT 'user',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, user_id)
            );
            """
        )
    except Exception as exc:
        _gateway_log.warning("Telegram Guard: no se pudo inicializar authorized_users: %s", exc)
    try:
        ensure_vault_registry()
    except Exception as exc:
        _gateway_log.warning("Multi-Vault: no se pudo inicializar user_vaults: %s", exc)
    yield
    await app.state.redis.aclose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="API unificada para n8n, Telegram, agentes y escrituras DuckDB.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
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


# ── Locks por chat (concurrencia por grupo) ────────────────────────────────────

@asynccontextmanager
async def _chat_lock(chat_id: str):
    """
    Mutex por chat_id usando Redis (si está disponible).

    - Clave: lock:chat:{chat_id}
    - timeout: evita locks huérfanos si el proceso muere durante la ejecución.
    - blocking_timeout: tiempo máximo esperando el lock antes de soltar y continuar.
    """
    redis_client = getattr(app.state, "redis", None)
    if redis_client is None:
        # Sin Redis configurado: no aplicar mutex, pero no romper el flujo.
        yield
        return
    lock_key = f"lock:chat:{chat_id}"
    lock = redis_client.lock(lock_key, timeout=10, blocking_timeout=15)
    acquired = False
    try:
        acquired = await lock.acquire()
        yield
    finally:
        if acquired:
            try:
                await lock.release()
            except Exception:
                # No romper si no se puede liberar; expirará por timeout.
                pass


# ── Root y health ─────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "endpoints": [
            "/api/v1/agent/chat",
            "/api/v1/agent/{worker_id}/chat",
            "/api/v1/agent/workers",
            "/api/v1/agent/{worker_id}/history",
            "/api/v1/db/write",
            "/api/v1/homeostasis/status",
            "/api/v1/homeostasis/ask_task",
            "/api/v1/system/health",
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api-gateway"}


# ── System health ─────────────────────────────────────────────────────────────

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
        mlx = "ok"
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
    except Exception:
        return {"workers": ["finanz"]}


@app.get("/api/v1/agent/{worker_id}/history")
async def agent_history(worker_id: str, session_id: str = "default"):
    return {"history": [], "worker_id": worker_id}


def _resolve_chat_session_id(body: ChatRequest, req: Request) -> tuple[str, str]:
    """
    Identificador de hilo para estado por chat (sandbox, /team, auditoría).

    Orden: cuerpo JSON (chat_id y alias Pydantic) → query ?chat_id= / ?session_id=
    → cabeceras X-Chat-Id, X-Session-Id, X-Duckclaw-Chat-Id.
    """
    cid = (body.chat_id or "").strip()
    if cid:
        return cid, "body.chat_id"
    for key in ("chat_id", "session_id", "thread_id", "chatId"):
        raw = req.query_params.get(key)
        if raw and str(raw).strip():
            return str(raw).strip(), f"query.{key}"
    for header in ("X-Chat-Id", "X-Session-Id", "X-Duckclaw-Chat-Id"):
        raw = req.headers.get(header)
        if raw and str(raw).strip():
            return str(raw).strip(), f"header.{header}"
    return "default", "default"


def _escape_sql_literal(v: Any, max_len: int = 256) -> str:
    """
    Escape simple SQL string literals for DuckDB when we don't use parameterized queries.
    """
    s = "" if v is None else str(v)
    return s.replace("'", "''")[:max_len]


async def _lookup_whitelist_role(redis_client: Any, db: Any, tenant_id: str, user_id: str) -> Optional[str]:
    """
    Telegram Guard whitelist lookup with Redis cache (TTL=1h) + DuckDB source of truth.
    """
    key = f"whitelist:{tenant_id}:{user_id}"
    if redis_client is not None:
        try:
            cached = await redis_client.get(key)
            if cached:
                return str(cached).strip() or None
        except Exception:
            pass

    tid = _escape_sql_literal(tenant_id, max_len=128)
    uid = _escape_sql_literal(user_id, max_len=128)
    def _ensure_authorized_users_table() -> None:
        # Best-effort: usa el mismo `db` en el que estamos para evitar lock.
        try:
            db.execute(_AUTHORIZED_USERS_TABLE_DDL)
        except Exception:
            # No rompemos; el SELECT de abajo dará None.
            return

    try:
        raw = db.query(
            f"SELECT role FROM main.authorized_users WHERE tenant_id='{tid}' AND user_id='{uid}' LIMIT 1"
        )
        rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
        if rows and isinstance(rows[0], dict):
            role = (rows[0].get("role") or "").strip()
            if role:
                if redis_client is not None:
                    try:
                        await redis_client.set(key, role, ex=3600)
                    except Exception:
                        pass
                return role
    except Exception:
        # Si la tabla no existe todavía, crearla y reintentar una vez.
        _ensure_authorized_users_table()
        try:
            raw = db.query(
                f"SELECT role FROM main.authorized_users WHERE tenant_id='{tid}' AND user_id='{uid}' LIMIT 1"
            )
            rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
            if rows and isinstance(rows[0], dict):
                role = (rows[0].get("role") or "").strip()
                if role:
                    if redis_client is not None:
                        try:
                            await redis_client.set(key, role, ex=3600)
                        except Exception:
                            pass
                    return role
        except Exception:
            pass
    return None


def _send_security_alert_to_admin(user_id: str, tenant_id: str) -> None:
    """
    Alert opcional al admin via webhook n8n (best-effort).
    """
    admin_chat_id = (os.getenv("DUCKCLAW_ADMIN_CHAT_ID") or "").strip()
    webhook_url = (os.getenv("N8N_OUTBOUND_WEBHOOK_URL") or "").strip()
    auth_key = (os.getenv("N8N_AUTH_KEY") or getattr(settings, "N8N_AUTH_KEY", "") or "").strip()

    if not admin_chat_id or not webhook_url:
        _gateway_log.warning(
            "Telegram Guard: no se pudo enviar alerta (admin_chat_id=%r webhook=%r)",
            admin_chat_id,
            bool(webhook_url),
        )
        return

    text = f"🚨 Alerta de Seguridad: El usuario {user_id} ha intentado acceder 3 veces sin autorización al tenant {tenant_id}."
    headers: dict[str, Any] = {"Content-Type": "application/json"}
    if auth_key:
        headers["X-DuckClaw-Secret"] = auth_key

    payload = {"chat_id": str(admin_chat_id), "text": text}
    data = json.dumps(payload).encode("utf-8")
    req = _url_request.Request(webhook_url, data=data, headers=headers, method="POST")

    try:
        with _url_request.urlopen(req, timeout=10) as resp:
            _ = resp.read()
    except URLError as exc:
        _gateway_log.warning("Telegram Guard: error enviando alerta webhook: %s", exc)
    except Exception as exc:  # noqa: BLE001
        _gateway_log.warning("Telegram Guard: error enviando alerta webhook (unknown): %s", exc)


async def _authorize_or_reject(*, tenant_id: str, user_id: str, is_owner: bool) -> None:
    """
    Raises HTTPException(403) for unauthorized access.
    Also increments unauthorized attempts and triggers admin alert after 3 attempts.
    """
    # Check 1 (Bypass): owner bypass no DB/Redis access.
    if is_owner:
        _langsmith_auth_log(auth_status="authorized", user_id=user_id, tenant_id=tenant_id)
        return

    redis_client = getattr(app.state, "redis", None)
    from duckclaw.graphs.graph_server import get_db

    db = get_db()
    role = await _lookup_whitelist_role(redis_client, db, tenant_id, user_id)
    if role:
        _langsmith_auth_log(auth_status="authorized", user_id=user_id, tenant_id=tenant_id)
        return

    # PM2 visibility: ruido en logs, pero respuesta silenciosa en Telegram (n8n no debería reenviar un texto).
    _gateway_log.warning(
        "[SECURITY_ALERT] Unauthorized access attempt: user_id='%s' tenant_id='%s'",
        user_id,
        tenant_id,
    )
    _langsmith_auth_log(auth_status="unauthorized_attempt", user_id=user_id, tenant_id=tenant_id)

    # Contador para alertas del admin (best-effort).
    if redis_client is not None:
        attempts_key = f"authz_unauthorized_attempts:{tenant_id}:{user_id}"
        try:
            attempts = await redis_client.incr(attempts_key)
            # TTL 1h para evitar crecimiento infinito
            if attempts == 1:
                await redis_client.expire(attempts_key, 3600)
            if attempts >= 3 and attempts - 3 < 1:
                await asyncio.get_running_loop().run_in_executor(
                    None, _send_security_alert_to_admin, user_id, tenant_id
                )
        except Exception:
            pass

    raise HTTPException(
        status_code=403,
        detail="Acceso denegado. No tienes autorización para interactuar con este agente.",
    )


@app.post("/api/v1/agent/chat")
@app.post("/api/v1/agent/{worker_id}/chat")
async def agent_chat(
    http_request: Request,
    worker_id: Optional[str] = None,
    body: ChatRequest | None = None,
):
    """
    Endpoint de chat multi-usuario.

    Recibe ChatRequest (message, chat_id, user_id, username, chat_type, history, stream)
    y mapea chat_id → session_id interno.
    Si el JSON no trae chat_id, se usan query params o cabeceras (ver _resolve_chat_session_id).
    """
    if body is None:
        body = ChatRequest(message="", chat_id="default", user_id="system", username="system", chat_type="private")
    session_id, session_source = _resolve_chat_session_id(body, http_request)
    if session_source == "default" and not (body.chat_id or "").strip():
        _gateway_log.warning(
            "[session] chat_id/session_id ausente; usando 'default' (source=%s). "
            "El estado por chat (/sandbox) no coincidirá con otros mensajes. "
            "Añade chat_id al body, ?chat_id= en la URL, o cabecera X-Chat-Id.",
            session_source,
        )
    else:
        _gateway_log.info(
            f"[session] chat_id resolved: {_c_chat_id(session_id)} (source={session_source})"
        )
    tenant_id = (body.tenant_id or "default").strip() or "default"
    return await _invoke_chat(body, worker_id or "finanz", session_id=session_id, tenant_id=tenant_id)


def _truncate_log(s: str, max_len: int = 200) -> str:
    s = (s or "").strip()
    return s if len(s) <= max_len else s[:max_len] + "..."


def _strip_markdown_bold(s: str) -> str:
    """Quita asteriscos de negrita Markdown (**texto**) para respuesta más limpia."""
    if not s or not isinstance(s, str):
        return s
    return re.sub(r"\*\*([^*]*)\*\*", r"\1", s)


def clean_agent_response(response: str) -> str:
    """
    Limpia menús residuales del LLM para que la respuesta final sea concisa.
    Elimina bloques tipo \"¿Cuál es mi tarea?\", \"Puedo ayudarte con:\" y menús de resumen financiero.
    """
    if not response or not isinstance(response, str):
        return response
    text = str(response)
    patterns = [
        r"¿Cuál\s+es\s+mi\s+tarea\?.*",
        r"Puedo\s+ayudarte\s+con:.*",
        r"¿Qué\s+te\s+gustaría\s+hacer\s+ahora\?.*",
        r"-\s*📊\s*Resumen\s+financiero.*",
        r"-\s*💰\s*Registrar\s+transacciones.*",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip()


async def _invoke_chat(payload: ChatRequest, worker_id: str, session_id: str, tenant_id: str):
    """
    Orquesta la llamada al grafo LangGraph a partir de un ChatRequest.

    - session_id: ya resuelto (body + query + headers); debe ser el mismo en todos los POST del hilo.
    """
    message = (payload.message or "").strip()
    session_id = (session_id or "default").strip() or "default"
    tenant_id = (tenant_id or "default").strip() or "default"
    # Campos opcionales: defaults resilientes
    chat_type = (payload.chat_type or "private").strip().lower() or "private"
    username = (payload.username or "Usuario").strip() or "Usuario"
    user_id = (payload.user_id or "").strip()
    vault_user_id = user_id or session_id
    _, vault_db_path = resolve_active_vault(vault_user_id)
    history = payload.history or []
    is_system_prompt = bool(payload.is_system_prompt or False)

    _gateway_log.info(f"in(chat_id={_c_chat_id(session_id)}): {_truncate_log(message)}")

    # Telegram Guard: autoriza antes de ejecutar comandos (/team, /sandbox, etc.)
    # y antes de invocar cualquier lógica LangGraph.
    if not is_system_prompt:
        owner_user_id = (os.getenv("DUCKCLAW_OWNER_ID") or os.getenv("DUCKCLAW_ADMIN_CHAT_ID") or "").strip()
        is_owner = bool(owner_user_id and user_id and str(user_id).strip() == str(owner_user_id).strip())
        await _authorize_or_reject(
            tenant_id=tenant_id,
            user_id=user_id,
            is_owner=is_owner,
        )

    msg_stripped = (message or "").strip()
    # No invocar el grafo con mensaje vacío (evita plan vacío y respuesta "¿Cuál es mi tarea?")
    if not msg_stripped:
        return {
            "response": "No recibí ningún mensaje. Escribe tu consulta o comando (por ejemplo /tasks).",
            "session_id": session_id,
            "worker_id": worker_id,
            "elapsed_ms": 0,
        }
    if msg_stripped.startswith("/"):
        try:
            from duckclaw.graphs.on_the_fly_commands import handle_command
            from duckclaw.graphs.graph_server import get_db
            db = get_db()
            cmd_reply = handle_command(
                db,
                session_id,
                message,
                requester_id=user_id,
                tenant_id=tenant_id,
                vault_user_id=vault_user_id,
            )
            if cmd_reply is not None:
                _gateway_log.info("fly: %s", _truncate_log(cmd_reply))
                return {
                    "response": cmd_reply,
                    "session_id": session_id,
                    "worker_id": worker_id,
                    "elapsed_ms": 0,
                }
        except Exception as exc:
            _gateway_log.error("fly command failed: %s", exc)

    try:
        from duckclaw.graphs.graph_server import _get_or_build_graph, _ainvoke
    except Exception as exc:
        _gateway_log.error("graph init failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(status_code=503, detail=f"Error inicializando el grafo: {exc}")

    # Concurrencia: procesar un solo mensaje por chat_id a la vez.
    async with _chat_lock(session_id):
        try:
            graph = _get_or_build_graph()
        except Exception as exc:
            _gateway_log.error("graph init failed: %s\n%s", exc, traceback.format_exc())
            raise HTTPException(status_code=503, detail=f"Error inicializando el grafo: {exc}")

        try:
            from duckclaw.graphs.activity import set_busy, set_idle
            set_busy(session_id, task=message)
        except Exception:
            pass
        t0 = time.monotonic()
        try:
            result = await _ainvoke(
                graph,
                message,
                history or [],
                session_id,
                tenant_id=tenant_id,
                user_id=vault_user_id,
                vault_db_path=vault_db_path,
                is_system_prompt=is_system_prompt,
            )
        except Exception as exc:
            try:
                from duckclaw.graphs.activity import set_idle
                set_idle(session_id)
            except Exception:
                pass
            try:
                from duckclaw.graphs.on_the_fly_commands import append_task_audit, get_worker_id_for_chat
                from duckclaw.graphs.graph_server import get_db
                db = get_db()
                wid = get_worker_id_for_chat(db, session_id) or worker_id
                elapsed_fail = int((time.monotonic() - t0) * 1000)
                append_task_audit(db, session_id, wid, message, "FAILED", elapsed_fail)
            except Exception:
                pass
            try:
                if os.environ.get("DUCKCLAW_SAVE_CONVERSATION_TRACES", "true").strip().lower() in ("true", "1", "yes"):
                    from duckclaw.graphs.conversation_traces import append_conversation_trace
                    from duckclaw.graphs.on_the_fly_commands import get_effective_system_prompt
                    from duckclaw.graphs.graph_server import get_db
                    _db = get_db()
                    _sys = (get_effective_system_prompt(_db, worker_id) or "").strip()
                    _sys = _sys or (os.environ.get("DUCKCLAW_SYSTEM_PROMPT") or "").strip() or None
                    append_conversation_trace(
                        session_id, message, str(exc)[:8192],
                        worker_id=worker_id, elapsed_ms=elapsed_fail, status="FAILED",
                        system_prompt=_sys,
                    )
            except Exception:
                pass
            _gateway_log.error("agent_chat failed: %s\n%s", exc, traceback.format_exc())
            raise HTTPException(status_code=500, detail=str(exc))

        try:
            from duckclaw.graphs.activity import set_idle
            set_idle(session_id)
        except Exception:
            pass
    reply_text = result.get("reply", "") if isinstance(result, dict) else (result or "")
    _gateway_log.info(f"out(chat_id={_c_chat_id(session_id)}): {_truncate_log(reply_text)}")
    reply_text = _strip_markdown_bold(reply_text or "")
    # Filtro UX: eliminar menús residuales del LLM antes de devolver al cliente
    reply_text = clean_agent_response(reply_text or "")
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    # Grafo manager devuelve assigned_worker_id; usarlo para respuesta y trazas
    effective_worker_id = result.get("assigned_worker_id", worker_id) if isinstance(result, dict) else worker_id
    try:
        if not result.get("_audit_done"):
            from duckclaw.graphs.on_the_fly_commands import append_task_audit, get_worker_id_for_chat
            from duckclaw.graphs.graph_server import get_db
            db = get_db()
            wid = get_worker_id_for_chat(db, session_id) or worker_id
            plan_title = result.get("plan_title") if isinstance(result, dict) else None
            append_task_audit(db, session_id, wid, message, "SUCCESS", elapsed_ms, plan_title=plan_title)
    except Exception:
        pass
    try:
        if os.environ.get("DUCKCLAW_SAVE_CONVERSATION_TRACES", "true").strip().lower() in ("true", "1", "yes"):
            from duckclaw.graphs.conversation_traces import append_conversation_trace
            from duckclaw.graphs.on_the_fly_commands import get_effective_system_prompt
            from duckclaw.graphs.graph_server import get_db
            trace_messages = result.get("messages") if isinstance(result, dict) else None
            db = get_db()
            system_from_prompt = (get_effective_system_prompt(db, effective_worker_id) or "").strip()
            system_for_trace = system_from_prompt or (os.environ.get("DUCKCLAW_SYSTEM_PROMPT") or "").strip() or None
            append_conversation_trace(
                session_id, message, reply_text or "",
                worker_id=effective_worker_id, elapsed_ms=elapsed_ms, status="SUCCESS",
                system_prompt=system_for_trace,
                messages=trace_messages,
            )
    except Exception:
        pass
    try:
        from duckclaw.graphs.on_the_fly_commands import _telegram_safe
        reply_text = _telegram_safe(reply_text)
    except Exception:
        pass
    return {
        "response": reply_text,
        "session_id": session_id,
        "worker_id": effective_worker_id or worker_id,
        "elapsed_ms": elapsed_ms,
    }


# ── Escrituras DuckDB (encolar en Redis) ──────────────────────────────────────

class WriteRequest(BaseModel):
    query: str = Field(..., description="Consulta SQL parametrizada")
    params: list = Field(default_factory=list, description="Parámetros para la consulta")
    tenant_id: str = Field(default="default", description="ID del tenant")
    user_id: str | None = Field(default=None, description="ID del usuario dueño de la bóveda")
    db_path: str | None = Field(default=None, description="Ruta DuckDB destino (bóveda activa)")


class EnqueueResponse(BaseModel):
    status: str
    task_id: str


@app.post("/api/v1/db/write", response_model=EnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_write(req: WriteRequest):
    """Encola escrituras para el DB Writer (evita bloqueos en DuckDB)."""
    if req.query.strip().upper().startswith("SELECT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las consultas SELECT deben ejecutarse directamente, no encolarse.",
        )
    task_id = str(uuid.uuid4())
    user_id = (req.user_id or "").strip() or "default"
    db_path = (req.db_path or "").strip()
    if db_path and not validate_user_db_path(user_id, db_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="db_path inválido para el usuario.",
        )
    if not db_path:
        _, db_path = resolve_active_vault(user_id)
    payload = {
        "task_id": task_id,
        "tenant_id": req.tenant_id,
        "user_id": user_id,
        "db_path": db_path,
        "query": req.query,
        "params": req.params,
    }
    try:
        await app.state.redis.lpush("duckdb_write_queue", json.dumps(payload))
        return EnqueueResponse(status="enqueued", task_id=task_id)
    except redis.RedisError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Error conectando al broker de mensajes: {str(e)}",
        )


# ── Quotes router (microservicio: routers en services/api-gateway) ───────────

try:
    from routers.quotes import router as quotes_router
    app.include_router(quotes_router)
except ImportError:
    pass

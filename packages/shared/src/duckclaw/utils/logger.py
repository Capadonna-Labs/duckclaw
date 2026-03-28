"""
Observabilidad 2.0: logging estructurado con contextvars (tenant, worker, chat_id).

Spec: specs/features/Observabilidad 2.0 (Logging Estructurado y Métricas).md
"""

from __future__ import annotations

import functools
import hashlib
import logging
import os
import re
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator, Optional, TypeVar

# ── Contexto asíncrono / por request ─────────────────────────────────────────

ctx_tenant: ContextVar[str] = ContextVar("tenant", default="default")
ctx_worker: ContextVar[str] = ContextVar("worker", default="manager")
ctx_chat: ContextVar[str] = ContextVar("chat_id", default="unknown")

_DEFAULT_TENANT = "default"
_DEFAULT_WORKER = "manager"
_DEFAULT_CHAT = "unknown"

# ANSI: columna chat en PM2; identidad `@alias (id)` usa dos tonos (alias vs id) y paleta 6×6×6 (216) para baja colisión.
_ANSI_RESET = "\033[0m"
# `@Nombre (session_id)` — el id puede ser numérico Telegram u otro texto sin paréntesis anidados.
_LOG_IDENTITY_RE = re.compile(r"^@(?P<alias>.+) \((?P<cid>[^)]+)\)\s*\Z")


def _terminal_chat_id_colors_enabled() -> bool:
    if os.environ.get("NO_COLOR", "").strip():
        return False
    if os.environ.get("DUCKCLAW_LOG_NO_COLOR", "").strip().lower() in ("1", "true", "yes"):
        return False
    return True


def _identity_seed(kind: str, alias: str, cid: str) -> int:
    blob = f"{kind}\x1e{alias}\x1e{cid}".encode("utf-8", errors="ignore")
    return int(hashlib.sha1(blob).hexdigest(), 16)


def _ansi_fg_216_idx(idx: int) -> str:
    """Color 16–231 (cubo RGB 6×6×6)."""
    n = idx % 216
    r = n // 36
    g = (n % 36) // 6
    b = n % 6
    code = 16 + 36 * r + 6 * g + b
    return f"\033[38;5;{code}m"


def _pair_distinct_alias_id_colors(alias: str, cid: str) -> tuple[str, str]:
    """Dos colores distintos: uno derivado del alias+id, otro del id+alias (semillas distintas)."""
    ia = _identity_seed("alias", alias, cid) % 216
    ib = _identity_seed("id", alias, cid) % 216
    if ia == ib:
        ib = (ib + 83) % 216
    return _ansi_fg_216_idx(ia), _ansi_fg_216_idx(ib)


def chat_id_color_code(chat_id: str) -> str:
    """Código ANSI estable por cadena (paleta 216 colores; compatible con logs históricos)."""
    seed = _identity_seed("plain", str(chat_id or "default"), "")
    return _ansi_fg_216_idx(seed)


def format_chat_identity_column_for_terminal(display: str) -> str:
    """
    Columna de log con color: si es `@alias (id)`, colorea @alias e id por separado (siempre distintos);
    si no coincide el patrón, un solo color derivado de la cadena completa (216 tonos).
    """
    s = (display or "").strip()
    if not s:
        s = "unknown"
    if not _terminal_chat_id_colors_enabled():
        return s
    m = _LOG_IDENTITY_RE.match(s)
    if m:
        alias, cid = m.group("alias"), m.group("cid")
        ca, cb = _pair_distinct_alias_id_colors(alias, cid)
        return f"{ca}@{alias}{_ANSI_RESET} ({cb}{cid}{_ANSI_RESET})"
    return f"{chat_id_color_code(s)}{s}{_ANSI_RESET}"


def format_chat_log_identity(chat_id: str | None, username: str | None = None) -> str:
    """
    Etiqueta humana para la tercera columna de logs PM2: @Alias (chat_id) si hay alias;
    si no, solo chat_id (misma convención que el API Gateway).
    """
    cid = str(chat_id if chat_id is not None else "").strip() or "unknown"
    uname = str(username or "").strip()
    return f"@{uname} ({cid})" if uname else cid


def format_chat_id_for_terminal(chat_id: str, *, as_repr: bool = False) -> str:
    """
    Identidad de chat con color para terminal (PM2). Con alias: dos tonos (@nombre vs id).
    ``as_repr=True`` envuelve en comillas ASCII (como ``out(chat_id=...)``); el interior sigue coloreado.
    Desactivar con NO_COLOR o DUCKCLAW_LOG_NO_COLOR=1.
    """
    raw = chat_id if chat_id is not None else "default"
    s = str(raw)
    if not _terminal_chat_id_colors_enabled():
        return repr(s) if as_repr else s
    inner = format_chat_identity_column_for_terminal(s)
    if as_repr:
        return f"'{inner}'"
    return inner

def set_log_context(
    *,
    tenant_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> None:
    """Establece tenant/worker/chat para las líneas de log subsiguientes."""
    if tenant_id is not None:
        ctx_tenant.set((tenant_id or "").strip() or _DEFAULT_TENANT)
    if worker_id is not None:
        ctx_worker.set((worker_id or "").strip() or _DEFAULT_WORKER)
    if chat_id is not None:
        ctx_chat.set((chat_id or "").strip() or _DEFAULT_CHAT)


def reset_log_context() -> None:
    """Restaura valores por defecto (útil en finally de middleware)."""
    ctx_tenant.set(_DEFAULT_TENANT)
    ctx_worker.set(_DEFAULT_WORKER)
    ctx_chat.set(_DEFAULT_CHAT)


@contextmanager
def structured_log_context(
    *,
    tenant_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> Iterator[None]:
    """Context manager: guarda y restaura tenant/worker/chat."""
    t_tok = w_tok = c_tok = None
    try:
        if tenant_id is not None:
            t_tok = ctx_tenant.set((tenant_id or "").strip() or _DEFAULT_TENANT)
        if worker_id is not None:
            w_tok = ctx_worker.set((worker_id or "").strip() or _DEFAULT_WORKER)
        if chat_id is not None:
            c_tok = ctx_chat.set((chat_id or "").strip() or _DEFAULT_CHAT)
        yield
    finally:
        if c_tok is not None:
            ctx_chat.reset(c_tok)
        if w_tok is not None:
            ctx_worker.reset(w_tok)
        if t_tok is not None:
            ctx_tenant.reset(t_tok)


class DuckClawLogFilter(logging.Filter):
    """Inyecta tenant, worker y chat_id en cada LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.tenant = ctx_tenant.get()
        record.worker = ctx_worker.get()
        record.chat_id = ctx_chat.get()
        return True


class DuckClawStructuredFormatter(logging.Formatter):
    """Formato: YYYY-MM-DD HH:MM:SS | [tenant:worker] | chat_id | message"""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s | [%(tenant)s:%(worker)s] | %(chat_id_colored)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "tenant"):
            record.tenant = ctx_tenant.get()
        if not hasattr(record, "worker"):
            record.worker = ctx_worker.get()
        if not hasattr(record, "chat_id"):
            record.chat_id = ctx_chat.get()
        cid = str(getattr(record, "chat_id", None) or ctx_chat.get() or "unknown")
        setattr(record, "chat_id_colored", format_chat_identity_column_for_terminal(cid))
        return super().format(record)


DEFAULT_STRUCTURED_LOGGERS: tuple[str, ...] = (
    "duckclaw.gateway",
    "duckclaw.obs",
    "duckclaw.graphs",
    "duckclaw.graphs.general_graph",
    "duckclaw.graphs.retail_graph",
    "duckclaw.graphs.manager_graph",
    "duckclaw.graphs.graph_server",
    "duckclaw.workers",
    "duckclaw.workers.factory",
    "duckclaw.fly",
    "duckclaw.forge",
    "duckclaw.forge.skills.ibkr_bridge",
    "duckclaw.bi.agent",
)


def configure_structured_logging(
    *,
    level: int = logging.INFO,
    logger_names: Optional[tuple[str, ...]] = None,
) -> None:
    """
    Configura formatter + filter en loggers DuckClaw (idempotente por logger).
    No modifica el root logger para no duplicar logs de uvicorn.
    """
    names = logger_names if logger_names is not None else DEFAULT_STRUCTURED_LOGGERS
    formatter = DuckClawStructuredFormatter()
    flt = DuckClawLogFilter()
    for name in names:
        log = logging.getLogger(name)
        log.setLevel(level)
        # Evitar duplicar handlers al re-ejecutar
        has_structured = any(
            getattr(h, "_duckclaw_structured", False) for h in log.handlers
        )
        if has_structured:
            continue
        h = logging.StreamHandler(sys.stdout)
        h.setLevel(level)
        h.setFormatter(formatter)
        h.addFilter(flt)
        setattr(h, "_duckclaw_structured", True)
        log.addHandler(h)
        log.propagate = False


def get_obs_logger(name: str = "duckclaw.obs") -> logging.Logger:
    """Logger recomendado para [REQ]/[PLAN]/[TOOL]/[RES]/[SYS]/[ERR]."""
    return logging.getLogger(name)


def log_req(logger: logging.Logger, msg: str, *args: Any, source: Optional[str] = None) -> None:
    """Log [REQ]. Si ``source`` (p. ej. ``body``), añade `` (via body)`` al final."""
    if source:
        logger.info("[REQ] " + msg + " (via %s)", *args, source)
    else:
        logger.info("[REQ] " + msg, *args)


def log_fly(logger: logging.Logger, msg: str, *args: Any) -> None:
    """Log on-the-fly / gateway commands con prefijo [FLY]."""
    logger.info("[FLY] " + msg, *args)


def log_plan(logger: logging.Logger, msg: str, *args: Any) -> None:
    logger.info("[PLAN] " + msg, *args)


def log_tool_msg(logger: logging.Logger, msg: str, *args: Any) -> None:
    logger.info("[TOOL] " + msg, *args)


def log_res(logger: logging.Logger, msg: str, *args: Any) -> None:
    logger.info("[RES] " + msg, *args)


def log_sys(logger: logging.Logger, msg: str, *args: Any) -> None:
    logger.info("[SYS] " + msg, *args)


def log_err(logger: logging.Logger, msg: str, *args: Any) -> None:
    logger.error("[ERR] " + msg, *args)


# ── Decoradores de latencia para tools (sync / async) ─────────────────────────

F = TypeVar("F", bound=Callable[..., Any])


def log_tool_execution_sync(func: Optional[F] = None, *, name: Optional[str] = None) -> Any:
    """
    Decorador síncrono: log [TOOL] name -> OK/FAILED con ⏱️ ms.
    Uso: @log_tool_execution_sync o @log_tool_execution_sync(name="read_sql")
    """

    def decorator(f: F) -> F:
        tool_name = name or getattr(f, "__name__", "tool")
        log = get_obs_logger()

        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = f(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                log.info("[TOOL] %s -> OK (⏱️ %.0fms)", tool_name, elapsed)
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                log.error("[TOOL] %s -> FAILED: %s (⏱️ %.0fms)", tool_name, e, elapsed)
                raise

        return wrapper  # type: ignore[return-value]

    if func is not None:
        return decorator(func)
    return decorator


def log_tool_execution_async(func: Optional[F] = None, *, name: Optional[str] = None) -> Any:
    """Decorador async para tools awaitables."""

    def decorator(f: F) -> F:
        tool_name = name or getattr(f, "__name__", "tool")
        log = get_obs_logger()

        @functools.wraps(f)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = await f(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                log.info("[TOOL] %s -> OK (⏱️ %.0fms)", tool_name, elapsed)
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                log.error("[TOOL] %s -> FAILED: %s (⏱️ %.0fms)", tool_name, e, elapsed)
                raise

        return wrapper  # type: ignore[return-value]

    if func is not None:
        return decorator(func)
    return decorator


def extract_usage_from_messages(messages: Optional[list[Any]]) -> Optional[dict[str, int]]:
    """
    Último AIMessage con usage_metadata (LangChain).
    Retorna dict con input_tokens, output_tokens, total_tokens o None.
    """
    if not messages:
        return None
    try:
        from langchain_core.messages import AIMessage
    except Exception:
        AIMessage = None  # type: ignore[assignment,misc]
    for m in reversed(messages):
        if AIMessage is not None and isinstance(m, AIMessage):
            meta = getattr(m, "usage_metadata", None) or {}
            if not meta:
                rmeta = getattr(m, "response_metadata", None) or {}
                if isinstance(rmeta, dict):
                    meta = rmeta.get("token_usage") or rmeta.get("usage") or {}
            if isinstance(meta, dict) and meta:
                inp = int(meta.get("input_tokens") or meta.get("prompt_tokens") or 0)
                out = int(meta.get("output_tokens") or meta.get("completion_tokens") or 0)
                tot = int(meta.get("total_tokens") or (inp + out) or 0)
                return {"input_tokens": inp, "output_tokens": out, "total_tokens": tot}
    return None

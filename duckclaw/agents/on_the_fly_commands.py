"""
On-the-Fly CLI: comandos de Telegram que mutan estado del grafo sin reiniciar.

Spec: specs/interfaz_de_comandos_dinamicos_On-the-Fly_CLI.md
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional, Tuple

_PREFIX = "chat_"


def _chat_key(chat_id: Any, suffix: str) -> str:
    """Key for agent_config; supports numeric (Telegram) and string (API session_id)."""
    try:
        cid = int(chat_id)
        return f"{_PREFIX}{cid}_{suffix}"
    except (TypeError, ValueError):
        return f"{_PREFIX}{str(chat_id)[:64]}_{suffix}"


_AGENT_CONFIG_TABLE = "agent_config"


def _ensure_agent_config(db: Any) -> None:
    db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_AGENT_CONFIG_TABLE} (
            key VARCHAR PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def get_chat_state(db: Any, chat_id: Any, key: str) -> str:
    """Read a chat-scoped config key from agent_config."""
    _ensure_agent_config(db)
    k = _chat_key(chat_id, key).replace("'", "''")[:200]
    try:
        r = db.query(f"SELECT value FROM {_AGENT_CONFIG_TABLE} WHERE key = '{k}' LIMIT 1")
        rows = json.loads(r) if isinstance(r, str) else (r or [])
        if rows and isinstance(rows[0], dict):
            return (rows[0].get("value") or "").strip()
    except Exception:
        pass
    return ""


def set_chat_state(db: Any, chat_id: Any, key: str, value: str) -> None:
    """Write a chat-scoped config key to agent_config."""
    _ensure_agent_config(db)
    k = _chat_key(chat_id, key).replace("'", "''")[:128]
    v = str(value).replace("'", "''")[:16384]
    db.execute(
        f"""
        INSERT INTO {_AGENT_CONFIG_TABLE} (key, value) VALUES ('{k}', '{v}')
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """
    )


def parse_command(text: str) -> Tuple[str, str]:
    """Parse /command or /command args. Returns (name, args)."""
    if not text or not text.strip().startswith("/"):
        return "", ""
    parts = text.strip().split(maxsplit=1)
    name = (parts[0] or "").lstrip("/").lower()
    args = (parts[1] if len(parts) > 1 else "").strip()
    return name, args


def execute_role_switch(db: Any, chat_id: Any, worker_id: str) -> str:
    """/role <worker_id>: cambia el rol (worker template) en caliente."""
    from duckclaw.workers.factory import list_workers
    available = list_workers()
    
    _esc = r"\_"
    wid = (worker_id or "").strip().lower()
    if not wid:
        avail_str = "\n".join(f"- {w.replace('_', _esc)}" for w in available) if available else "ninguna"
        return f"Uso: /role <worker\\_id>\n\nPlantillas disponibles:\n{avail_str}"
    if wid not in available:
        avail_str = "\n".join(f"- {w.replace('_', _esc)}" for w in available) if available else "ninguna"
        return f"Rol desconocido: {wid.replace('_', _esc)}.\n\nPlantillas disponibles:\n{avail_str}"
    try:
        from duckclaw.workers.manifest import load_manifest
        spec = load_manifest(wid)
        set_chat_state(db, chat_id, "worker_id", wid)
        skills = ", ".join(spec.skills_list) if spec.skills_list else "run_sql"
        return f"✅ Rol cambiado a {spec.name} ({wid}). Capacidades: {skills}."
    except Exception as e:
        return f"Error al cargar rol: {e}."


def execute_skills_list(db: Any, chat_id: Any) -> str:
    """/skills: lista herramientas actuales del agente."""
    wid = get_chat_state(db, chat_id, "worker_id")
    if wid:
        try:
            from duckclaw.workers.manifest import load_manifest
            spec = load_manifest(wid)
            lines = [f"• {s}" for s in spec.skills_list]
            lines.append("• run_sql")
            return f"**Rol:** {spec.name}\nHerramientas:\n" + "\n".join(lines)
        except Exception as e:
            return f"Error: {e}."
    return "Herramientas por defecto: run_sql, inspect_schema, manage_memory.\nUsa /role <worker_id> para cambiar de rol."


def execute_forget(db: Any, chat_id: Any) -> str:
    """/forget: borra historial de la conversación y reinicia estado."""
    try:
        cid = int(chat_id)
        # Telegram: chat_id is numeric, use telegram_conversation
        db.execute(f"DELETE FROM telegram_conversation WHERE chat_id = {cid}")
    except (TypeError, ValueError):
        # API gateway: session_id is string (e.g. "default"), use api_conversation
        sid = str(chat_id).replace("'", "''")[:256]
        try:
            db.execute(f"DELETE FROM api_conversation WHERE session_id = '{sid}'")
        except Exception:
            pass  # Table may not exist if only Telegram used
    try:
        set_chat_state(db, chat_id, "last_audit", "")
    except Exception:
        pass
    if os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true":
        try:
            import langsmith
            # Log evento Habeas Data (opcional: run_id no disponible aquí)
            pass
        except Exception:
            pass
    return "✅ Historial borrado. Contexto reiniciado (Habeas Data: supresión solicitada por el usuario)."


def execute_context_toggle(db: Any, chat_id: Any, on_off: str) -> str:
    """/context on|off: activa o desactiva inyección de memoria a largo plazo."""
    v = (on_off or "").strip().lower()
    if v in ("on", "1", "true", "sí", "si"):
        set_chat_state(db, chat_id, "use_rag", "true")
        return "✅ Contexto largo activado (más mensajes en historial)."
    if v in ("off", "0", "false"):
        set_chat_state(db, chat_id, "use_rag", "false")
        return "✅ Contexto largo desactivado (solo historial reciente)."
    current = get_chat_state(db, chat_id, "use_rag")
    return f"Uso: /context on | /context off\nEstado actual: {'on' if current != 'false' else 'off'}."


def execute_audit(db: Any, chat_id: Any) -> str:
    """/audit: evidencia de la última ejecución (SQL, latencia, run_id)."""
    raw = get_chat_state(db, chat_id, "last_audit")
    if not raw:
        return "No hay evidencia de última ejecución. Envía un mensaje y vuelve a usar /audit."
    try:
        data = json.loads(raw)
        sql = data.get("sql") or "(no registrado)"
        latency_ms = data.get("latency_ms") or "—"
        tokens = data.get("tokens") or "—"
        run_id = data.get("run_id") or "—"
        return (
            "📋 **Última ejecución**\n"
            f"SQL: `{str(sql)[:300]}`\n"
            f"Latencia: {latency_ms} ms\n"
            f"Tokens: {tokens}\n"
            f"LangSmith run_id: {run_id}"
        )
    except Exception:
        return "Datos de auditoría no válidos."


def execute_health(db: Any) -> str:
    """/health: estado de infraestructura (MLX, DuckDB, latencia)."""
    lines = []
    # DuckDB
    try:
        db.query("SELECT 1")
        lines.append("✅ DuckDB: conectado")
    except Exception as e:
        lines.append(f"❌ DuckDB: {e}")
    # MLX / inference
    base_url = os.environ.get("DUCKCLAW_LLM_BASE_URL", "").strip() or "http://127.0.0.1:8080"
    if base_url:
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        url = base + "/health"
        try:
            import urllib.request
            t0 = time.perf_counter()
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                elapsed = int((time.perf_counter() - t0) * 1000)
                lines.append(f"✅ Inferencia ({url[:40]}...): {elapsed} ms")
        except Exception as e:
            lines.append(f"⚠️ Inferencia: {e}")
    return "\n".join(lines) or "Sin comprobaciones."


def execute_approve_reject(db: Any, chat_id: Any, approved: bool) -> str:
    """/approve o /reject: HITL (grafo en interrupt). Sin interrupt implementado: mensaje informativo."""
    return "No hay operación pendiente de aprobación. (El grafo no está en estado interrupt en esta versión.)"


def _get_global_config(db: Any, key: str) -> str:
    """Read a global config key from agent_config (e.g. system_prompt)."""
    _ensure_agent_config(db)
    k = str(key).replace("'", "''")[:128]
    try:
        r = db.query(f"SELECT value FROM {_AGENT_CONFIG_TABLE} WHERE key = '{k}' LIMIT 1")
        rows = json.loads(r) if isinstance(r, str) else (r or [])
        if rows and isinstance(rows[0], dict):
            return (rows[0].get("value") or "").strip()
    except Exception:
        pass
    return ""


def _set_global_config(db: Any, key: str, value: str) -> None:
    """Write a global config key to agent_config."""
    _ensure_agent_config(db)
    k = str(key).replace("'", "''")[:128]
    v = str(value).replace("'", "''")[:16384]
    db.execute(
        f"""
        INSERT INTO {_AGENT_CONFIG_TABLE} (key, value) VALUES ('{k}', '{v}')
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """
    )


_PROVIDERS = ("mlx", "ollama", "openai", "anthropic", "deepseek", "groq")

# Modelo por defecto al cambiar provider (evita "Model Not Exist" al pasar de MLX a cloud)
_DEFAULT_MODEL_BY_PROVIDER = {
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-20241022",
    "groq": "llama-3.3-70b-versatile",
    "mlx": "",  # usa MLX_MODEL_ID o /v1/models
    "ollama": "llama3.2",
}


def execute_model(db: Any, chat_id: Any, args: str) -> str:
    """/model [provider=mlx] [model=...] [base_url=...]: cambia proveedor/modelo LLM en caliente. Sin args muestra el actual."""
    if not args or not args.strip():
        p = get_chat_state(db, chat_id, "llm_provider") or _get_global_config(db, "llm_provider")
        m = get_chat_state(db, chat_id, "llm_model") or _get_global_config(db, "llm_model")
        u = get_chat_state(db, chat_id, "llm_base_url") or _get_global_config(db, "llm_base_url")
        env_p = os.environ.get("DUCKCLAW_LLM_PROVIDER", "").strip()
        env_m = os.environ.get("DUCKCLAW_LLM_MODEL", "").strip()
        env_u = os.environ.get("DUCKCLAW_LLM_BASE_URL", "").strip()
        provider = p or env_p or "—"
        model = m or env_m or "—"
        base_url = (u or env_u or "—")[:50] + "…" if (u or env_u) and len((u or env_u) or "") > 50 else (u or env_u or "—")
        return f"Modelo actual:\n• provider: {provider}\n• model: {model}\n• base_url: {base_url}\n\nUso: /model provider=mlx | /model provider=deepseek | /model model=Slayer-8B"
    for part in args.split("|"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            k, v = k.strip().lower(), v.strip()
            if k == "provider":
                if v and v.lower() not in _PROVIDERS:
                    return f"Provider desconocido: {v}. Válidos: {', '.join(_PROVIDERS)}"
                set_chat_state(db, chat_id, "llm_provider", v)
                # Al cambiar provider, resetear model al default para evitar "Model Not Exist"
                # (ej. Slayer-8B-v1.1 no existe en DeepSeak)
                default_model = _DEFAULT_MODEL_BY_PROVIDER.get(v.lower(), "")
                set_chat_state(db, chat_id, "llm_model", default_model)
            elif k == "model":
                set_chat_state(db, chat_id, "llm_model", v)
            elif k == "base_url":
                set_chat_state(db, chat_id, "llm_base_url", v)
    return "✅ Modelo actualizado. Los próximos mensajes usarán esta config."


def execute_prompt(db: Any, chat_id: Any, new_prompt: str) -> str:
    """/prompt [nuevo system prompt]: cambia el system prompt en caliente. Sin argumentos muestra el actual."""
    if not new_prompt:
        current = _get_global_config(db, "system_prompt")
        if not current:
            wid = get_chat_state(db, chat_id, "worker_id")
            default_prompt = ""
            if wid:
                try:
                    from duckclaw.workers.manifest import load_manifest
                    from duckclaw.workers.loader import load_system_prompt
                    spec = load_manifest(wid)
                    default_prompt = load_system_prompt(spec)
                except Exception:
                    pass
            if default_prompt:
                preview = default_prompt[:400] + "..." if len(default_prompt) > 400 else default_prompt
                # Escapar underscores para no romper markdown
                preview = preview.replace("_", r"\_")
                return f"System prompt actual (predeterminado de {wid}):\n{preview}\n\nPara cambiar: /prompt <tu texto>"
            return "System prompt actual: (vacío — se usa el por defecto del bot).\nPara cambiar: /prompt <tu texto>"
        preview = current[:400] + "..." if len(current) > 400 else current
        preview = preview.replace("_", r"\_")
        return f"System prompt actual (modificado):\n{preview}\n\nPara cambiar: /prompt <nuevo texto>"
    _set_global_config(db, "system_prompt", new_prompt)
    preview = new_prompt[:200] + "..." if len(new_prompt) > 200 else new_prompt
    preview = preview.replace("_", r"\_")
    return f"✅ System prompt actualizado.\nVista previa: {preview}"


def handle_command(db: Any, chat_id: Any, text: str) -> Optional[str]:
    """
    Middleware: si el mensaje es un comando on-the-fly, ejecuta y retorna la respuesta.
    Si no es comando o no es manejado, retorna None.
    """
    name, args = parse_command(text)
    if not name:
        return None
    if name == "role":
        return execute_role_switch(db, chat_id, args)
    if name == "skills":
        return execute_skills_list(db, chat_id)
    if name == "forget":
        return execute_forget(db, chat_id)
    if name == "context":
        return execute_context_toggle(db, chat_id, args)
    if name == "audit":
        return execute_audit(db, chat_id)
    if name == "health":
        return execute_health(db)
    if name == "approve":
        return execute_approve_reject(db, chat_id, True)
    if name == "reject":
        return execute_approve_reject(db, chat_id, False)
    if name in ("prompt", "system_prompt", "system"):
        return execute_prompt(db, chat_id, args)
    if name in ("model", "provider", "llm"):
        return execute_model(db, chat_id, args)
    return None


def get_history_limit_for_chat(db: Any, chat_id: Any, default: int = 10) -> int:
    """Devuelve el límite de historial según use_rag del chat (para /context off = menos contexto)."""
    use_rag = get_chat_state(db, chat_id, "use_rag")
    if use_rag == "false":
        return 3
    return default


def get_worker_id_for_chat(db: Any, chat_id: Any) -> str:
    """Devuelve el worker_id asignado a este chat (vacío = grafo por defecto)."""
    return get_chat_state(db, chat_id, "worker_id")


def save_last_audit(db: Any, chat_id: Any, latency_ms: int, sql: str = "", run_id: str = "", tokens: Any = None) -> None:
    """Guarda datos de la última ejecución para /audit."""
    data = {"latency_ms": latency_ms, "sql": sql or "", "run_id": run_id or "", "tokens": tokens or ""}
    set_chat_state(db, chat_id, "last_audit", json.dumps(data))

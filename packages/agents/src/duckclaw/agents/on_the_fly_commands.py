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

# Caracteres que Telegram Markdown/MarkdownV2 interpretan; escapar para evitar "Can't find end of entity"
# MarkdownV2 requiere: _ * [ ] ( ) ~ ` > # + - = | { } . !
_TELEGRAM_MD_ESCAPE = ("\\", "_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!")


def _telegram_safe(text: str) -> str:
    """Escapa caracteres para que el texto sea seguro con parse_mode=Markdown o MarkdownV2 en Telegram."""
    if not text:
        return ""
    t = str(text)
    # Escapar backslash primero para evitar doble escape
    t = t.replace("\\", "\\\\")
    for c in _TELEGRAM_MD_ESCAPE:
        if c == "\\":
            continue
        t = t.replace(c, "\\" + c)
    return t


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


_DEFAULT_WORKER = "personalizable"


def execute_role_switch(db: Any, chat_id: Any, worker_id: str) -> str:
    """/role <worker_id>: cambia el rol (worker template) en caliente. Sin args: muestra rol actual y disponibles."""
    from duckclaw.workers.factory import list_workers
    available = list_workers()
    available = [_DEFAULT_WORKER] + [w for w in available if w != _DEFAULT_WORKER]
    wid = (worker_id or "").strip().lower()
    if not wid:
        current = get_chat_state(db, chat_id, "worker_id") or _DEFAULT_WORKER
        try:
            from duckclaw.workers.manifest import load_manifest
            spec = load_manifest(current)
            current_display = _telegram_safe(f"{spec.name} ({current})")
        except Exception:
            current_display = _telegram_safe(current)
        avail_str = "\n".join(f"\\- {_telegram_safe(w)}" for w in available) if available else "ninguna"
        return f"{_telegram_safe('Rol actual:')} {current_display}\n\n{_telegram_safe('Plantillas disponibles:')}\n{avail_str}\n\n{_telegram_safe('Uso: /role <worker_id>')}"
    if wid not in available:
        avail_str = "\n".join(f"\\- {_telegram_safe(w)}" for w in available) if available else "ninguna"
        return _telegram_safe(f"Rol desconocido: {wid}.") + f"\n\n{_telegram_safe('Plantillas disponibles:')}\n{avail_str}"
    try:
        from duckclaw.workers.manifest import load_manifest
        spec = load_manifest(wid)
        set_chat_state(db, chat_id, "worker_id", wid)
        skills = ", ".join(_telegram_safe(s) for s in (spec.skills_list or [])) or "run_sql"
        return _telegram_safe(f"✅ Rol cambiado a {spec.name} ({wid}). Capacidades: {skills}.")
    except Exception as e:
        return f"Error al cargar rol: {e}."


def execute_skills_list(db: Any, chat_id: Any) -> str:
    """/skills: lista herramientas actuales del agente. Texto seguro para Telegram (n8n)."""
    wid = get_chat_state(db, chat_id, "worker_id")
    if wid:
        try:
            from duckclaw.workers.manifest import load_manifest
            spec = load_manifest(wid)
            skills_safe = [_telegram_safe(s) for s in (spec.skills_list or [])]
            lines = [f"- {s}" for s in skills_safe]
            lines.append(f"- {_telegram_safe('run_sql')}")
            lines = [f"\\- {s}" for s in skills_safe]
            lines.append(f"\\- {_telegram_safe('run_sql')}")
            return _telegram_safe(f"Rol: {spec.name}\nHerramientas:") + "\n" + "\n".join(lines)
        except Exception as e:
            return f"Error: {e}."
    return _telegram_safe("Herramientas por defecto: run_sql, inspect_schema, manage_memory.\nUsa /role <worker_id> para cambiar de rol.")


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
    return _telegram_safe("✅ Historial borrado. Contexto reiniciado (Habeas Data: supresión solicitada por el usuario).")


def execute_context_toggle(db: Any, chat_id: Any, on_off: str) -> str:
    """/context on|off: activa o desactiva inyección de memoria a largo plazo."""
    v = (on_off or "").strip().lower()
    if v in ("on", "1", "true", "sí", "si"):
        set_chat_state(db, chat_id, "use_rag", "true")
        return _telegram_safe("✅ Contexto largo activado (más mensajes en historial).")
    if v in ("off", "0", "false"):
        set_chat_state(db, chat_id, "use_rag", "false")
        return _telegram_safe("✅ Contexto largo desactivado (solo historial reciente).")
    current = get_chat_state(db, chat_id, "use_rag")
    return _telegram_safe(f"Uso: /context on | /context off\nEstado actual: {'on' if current != 'false' else 'off'}.")


def execute_audit(db: Any, chat_id: Any) -> str:
    """/audit: evidencia de la última ejecución (SQL, latencia, run_id)."""
    raw = get_chat_state(db, chat_id, "last_audit")
    if not raw:
        return _telegram_safe("No hay evidencia de última ejecución. Envía un mensaje y vuelve a usar /audit.")
    try:
        data = json.loads(raw)
        sql = data.get("sql") or "(no registrado)"
        latency_ms = data.get("latency_ms") or "—"
        tokens = data.get("tokens") or "—"
        run_id = data.get("run_id") or "—"
        return _telegram_safe(
            f"📋 Última ejecución\nSQL: {str(sql)[:300]}\nLatencia: {latency_ms} ms\nTokens: {tokens}\nLangSmith run_id: {run_id}"
        )
    except Exception:
        return _telegram_safe("Datos de auditoría no válidos.")


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
    return _telegram_safe("\n".join(lines) or "Sin comprobaciones.")


def execute_approve_reject(db: Any, chat_id: Any, approved: bool) -> str:
    """/approve o /reject: HITL (grafo en interrupt). Sin interrupt implementado: mensaje informativo."""
    return _telegram_safe("No hay operación pendiente de aprobación. (El grafo no está en estado interrupt en esta versión.)")


def execute_goals(db: Any, chat_id: Any, args: str) -> str:
    """/goals [--reset]: consulta creencias del HomeostasisManager. --reset borra observed_value."""
    wid = get_chat_state(db, chat_id, "worker_id")
    if not wid:
        return _telegram_safe("Usa /role <worker_id> para asignar un rol con homeostasis (ej. finanz, powerseal).")
    try:
        from duckclaw.workers.manifest import load_manifest
        from duckclaw.workers.loader import run_schema
        from duckclaw.forge.homeostasis.belief_registry import BeliefRegistry
        from duckclaw.forge.homeostasis.surprise import compute_surprise
        spec = load_manifest(wid)
        run_schema(db, spec)  # Asegura que schema y agent_beliefs existan
        schema = spec.schema_name
        config = getattr(spec, "homeostasis_config", None) or {}
        registry = BeliefRegistry.from_config(config)
        if not registry.beliefs:
            return _telegram_safe(f"El rol {wid} no tiene creencias definidas en homeostasis.")
    except Exception as e:
        return _telegram_safe(f"Error al cargar homeostasis: {e}.")

    do_reset = (args or "").strip().lower() == "--reset"
    if do_reset:
        try:
            for b in registry.beliefs:
                key_safe = "".join(c if c.isalnum() or c == "_" else "_" for c in b.key.strip())
                db.execute(
                    f"UPDATE {schema}.agent_beliefs SET observed_value = NULL WHERE belief_key = '{key_safe}'"
                )
            return _telegram_safe("✅ Creencias reiniciadas (observed_value borrado).")
        except Exception as e:
            return _telegram_safe(f"Error al resetear: {e}.")

    lines = [f"Objetivos ({wid}):"]
    try:
        for b in registry.beliefs:
            key_safe = "".join(c if c.isalnum() or c == "_" else "_" for c in b.key.strip())
            r = db.query(
                f"SELECT belief_key, target_value, observed_value, threshold FROM {schema}.agent_beliefs "
                f"WHERE belief_key = '{key_safe}' LIMIT 1"
            )
            rows = json.loads(r) if isinstance(r, str) else (r or [])
            observed = None
            if rows and isinstance(rows[0], dict):
                row = rows[0]
                try:
                    observed = float(row.get("observed_value")) if row.get("observed_value") is not None else None
                except (TypeError, ValueError):
                    pass
            target = b.target
            thresh = b.threshold
            if observed is not None:
                res = compute_surprise(observed, target, thresh)
                status = "⚠️ anomalía" if res.is_anomaly else "✅ equilibrio"
                lines.append(
                    f"\\- {_telegram_safe(b.key)}: target={target}, observed={observed}, delta={res.delta:.4f} {status}"
                )
            else:
                lines.append(f"\\- {_telegram_safe(b.key)}: target={target}, threshold={thresh} (sin dato observado)")
    except Exception as e:
        return _telegram_safe(f"Error al leer creencias: {e}.")
    full = "\n".join(lines) + "\n\n/goals --reset para reiniciar."
    return _telegram_safe(full)


def execute_tasks(db: Any, chat_id: Any) -> str:
    """/tasks: estado del ActivityManager (Redis): IDLE, BUSY, tarea actual, tiempo en ejecución."""
    from duckclaw.agents.activity import get_activity
    data = get_activity(chat_id)
    if data is None:
        return _telegram_safe("Estado: IDLE (sin Redis para ActivityManager). Configura DUCKCLAW_WRITE_QUEUE_URL o DUCKCLAW_REDIS_URL.")
    status = data.get("status", "IDLE")
    task = data.get("task", "")
    started_at = data.get("started_at", 0)
    elapsed = ""
    if started_at and status == "BUSY":
        try:
            elapsed_sec = int(time.time()) - int(started_at)
            elapsed = _telegram_safe(f"\nTiempo: {elapsed_sec} s")
        except Exception:
            pass
    task_preview = _telegram_safe(str(task)[:80]) if task else _telegram_safe("—")
    return _telegram_safe(f"Estado: {status}") + elapsed + "\n" + _telegram_safe("Tarea: ") + task_preview


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
        return _telegram_safe(f"Modelo actual:\n- provider: {provider}\n- model: {model}\n- base_url: {base_url}\n\nUso: /model provider=mlx | /model provider=deepseek | /model model=Slayer-8B")
    for part in args.split("|"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            k, v = k.strip().lower(), v.strip()
            if k == "provider":
                if v and v.lower() not in _PROVIDERS:
                    return _telegram_safe(f"Provider desconocido: {v}. Válidos: {', '.join(_PROVIDERS)}")
                set_chat_state(db, chat_id, "llm_provider", v)
                # Al cambiar provider, resetear model al default para evitar "Model Not Exist"
                # (ej. Slayer-8B-v1.1 no existe en DeepSeak)
                default_model = _DEFAULT_MODEL_BY_PROVIDER.get(v.lower(), "")
                set_chat_state(db, chat_id, "llm_model", default_model)
            elif k == "model":
                set_chat_state(db, chat_id, "llm_model", v)
            elif k == "base_url":
                set_chat_state(db, chat_id, "llm_base_url", v)
    return _telegram_safe("✅ Modelo actualizado. Los próximos mensajes usarán esta config.")


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
                return _telegram_safe(f"System prompt actual (predeterminado de {wid}):\n{preview}\n\nPara cambiar: /prompt <tu texto>")
            return _telegram_safe("System prompt actual: (vacío — se usa el por defecto del bot).\nPara cambiar: /prompt <tu texto>")
        preview = current[:400] + "..." if len(current) > 400 else current
        return _telegram_safe(f"System prompt actual (modificado):\n{preview}\n\nPara cambiar: /prompt <nuevo texto>")
    _set_global_config(db, "system_prompt", new_prompt)
    preview = new_prompt[:200] + "..." if len(new_prompt) > 200 else new_prompt
    return _telegram_safe(f"✅ System prompt actualizado.\nVista previa: {preview}")


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
    if name == "setup":
        return _execute_setup(db, chat_id, args)
    if name == "goals":
        return execute_goals(db, chat_id, args)
    if name == "tasks":
        return execute_tasks(db, chat_id)
    if name == "history":
        return execute_history(db, chat_id, args)
    return None


def _execute_setup(db: Any, chat_id: Any, args: str) -> str:
    """/setup [key=value | key=value]: formato compatible con Telegram. Sin args muestra config."""
    if not args or not args.strip():
        p = get_chat_state(db, chat_id, "llm_provider") or _get_global_config(db, "llm_provider")
        m = get_chat_state(db, chat_id, "llm_model") or _get_global_config(db, "llm_model")
        wid = get_chat_state(db, chat_id, "worker_id")
        prompt = _get_global_config(db, "system_prompt") or ""
        return _telegram_safe(
            f"Config actual:\n- llm_provider: {p or '—'}\n- llm_model: {m or '—'}\n"
            f"- worker_id: {wid or '—'}\n- system_prompt: {prompt[:80]}...\n\n"
            "Para cambiar: /setup llm_provider=deepseek | /setup system_prompt=..."
        )
    for part in args.split("|"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            k, v = k.strip().lower(), v.strip()
            if k in ("llm_provider", "provider"):
                if v and v.lower() not in _PROVIDERS:
                    return _telegram_safe(f"Provider desconocido: {v}. Válidos: {', '.join(_PROVIDERS)}")
                set_chat_state(db, chat_id, "llm_provider", v)
                default_model = _DEFAULT_MODEL_BY_PROVIDER.get(v.lower(), "")
                set_chat_state(db, chat_id, "llm_model", default_model)
            elif k in ("llm_model", "model"):
                set_chat_state(db, chat_id, "llm_model", v)
            elif k in ("llm_base_url", "base_url"):
                set_chat_state(db, chat_id, "llm_base_url", v)
            elif k in ("system_prompt", "prompt"):
                _set_global_config(db, "system_prompt", v)
    return _telegram_safe("✅ Config actualizado.")


def get_history_limit_for_chat(db: Any, chat_id: Any, default: int = 10) -> int:
    """Devuelve el límite de historial según use_rag del chat (para /context off = menos contexto)."""
    use_rag = get_chat_state(db, chat_id, "use_rag")
    if use_rag == "false":
        return 3
    return default


def get_worker_id_for_chat(db: Any, chat_id: Any) -> str:
    """Devuelve el worker_id asignado a este chat. Por defecto: personalizable."""
    return get_chat_state(db, chat_id, "worker_id") or _DEFAULT_WORKER


def save_last_audit(db: Any, chat_id: Any, latency_ms: int, sql: str = "", run_id: str = "", tokens: Any = None) -> None:
    """Guarda datos de la última ejecución para /audit."""
    data = {"latency_ms": latency_ms, "sql": sql or "", "run_id": run_id or "", "tokens": tokens or ""}
    set_chat_state(db, chat_id, "last_audit", json.dumps(data))


_TASK_AUDIT_TABLE = "task_audit_log"


def _ensure_task_audit_log(db: Any) -> None:
    db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TASK_AUDIT_TABLE} (
            task_id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            worker_id VARCHAR,
            query_prefix VARCHAR,
            status VARCHAR NOT NULL,
            duration_ms INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def append_task_audit(
    db: Any,
    tenant_id: Any,
    worker_id: str,
    query_prefix: str,
    status: str,
    duration_ms: int,
) -> None:
    """Append a task to task_audit_log for /history. Spec: Fly comando history (Auditoría de Rendimiento)."""
    import uuid
    _ensure_task_audit_log(db)
    task_id = f"TASK-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    tenant_s = str(tenant_id).replace("'", "''")[:128]
    worker_s = (worker_id or "").replace("'", "''")[:64]
    prefix_s = (query_prefix or "")[:256].replace("'", "''")
    status_s = (status or "SUCCESS").upper().replace("'", "''")[:32]
    status_s = "SUCCESS" if status_s not in ("SUCCESS", "FAILED") else status_s
    db.execute(
        f"""
        INSERT INTO {_TASK_AUDIT_TABLE} (task_id, tenant_id, worker_id, query_prefix, status, duration_ms)
        VALUES ('{task_id}', '{tenant_s}', '{worker_s}', '{prefix_s}', '{status_s}', {int(duration_ms)})
        """
    )


def _is_simple_greeting(prefix: str) -> bool:
    """True si el mensaje es un saludo corto (hola, hi, etc.) sin tarea real."""
    p = (prefix or "").strip().lower()[:50]
    if len(p) > 35:
        return False
    greetings = (
        "hola", "hi", "hey", "hello", "buenas", "qué tal", "que tal",
        "buenos días", "buenos dias", "buenas tardes", "buenas noches",
        "ola", "saludos", "ciao", "adios", "chao",
    )
    return p in greetings or p.rstrip("!?.") in greetings


def _is_complex_task(row: dict) -> bool:
    """True si la tarea usó herramientas (tool use) o no es un saludo simple."""
    prefix = (row.get("query_prefix") or "").strip()
    if _is_simple_greeting(prefix):
        return False
    try:
        dur_ms = int(row.get("duration_ms") or 0)
    except (TypeError, ValueError):
        dur_ms = 0
    return dur_ms >= 1500 or len(prefix) > 20


def execute_history(db: Any, chat_id: Any, args: str) -> str:
    """/history [n]: historial de tareas complejas (tool use). Saludos simples (hola) se muestran como máximo uno."""
    tenant_s = str(chat_id).replace("'", "''")[:128]
    try:
        n = int((args or "5").strip())
        n = max(1, min(n, 20))
    except ValueError:
        n = 5
    _ensure_task_audit_log(db)
    try:
        r = db.query(
            f"""
            SELECT task_id, query_prefix, status, duration_ms, created_at
            FROM {_TASK_AUDIT_TABLE}
            WHERE tenant_id = '{tenant_s}'
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
        rows = json.loads(r) if isinstance(r, str) else (r or [])
    except Exception as e:
        return _telegram_safe(f"Error al cargar historial: {e}.")

    if not rows:
        return _telegram_safe("No hay tareas registradas.")

    # Filtrar: tareas complejas + como máximo 1 saludo simple
    complex_rows = []
    one_greeting = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _is_complex_task(row):
            complex_rows.append(row)
        elif one_greeting is None and _is_simple_greeting(row.get("query_prefix") or ""):
            one_greeting = row
    filtered = complex_rows[:n]
    if one_greeting is not None and len(filtered) < n:
        filtered.append(one_greeting)

    if not filtered:
        return _telegram_safe("No hay tareas complejas registradas (solo saludos o consultas muy breves).")

    lines = [f"Historial de tareas complejas (últimas {len(filtered)}):"]
    for i, row in enumerate(filtered, 1):
        if not isinstance(row, dict):
            continue
        task_id = row.get("task_id") or "—"
        prefix = (row.get("query_prefix") or "").strip()[:60]
        status = (row.get("status") or "UNKNOWN").upper()
        try:
            dur_ms = int(row.get("duration_ms") or 0)
        except (TypeError, ValueError):
            dur_ms = 0
        dur_s = f"{dur_ms / 1000:.1f}s"
        icon = "✅" if status == "SUCCESS" else "❌"
        lines.append(f"{i}. {_telegram_safe(str(task_id)[:20])} | {icon} {status} | ⏱️ {dur_s}")
        if prefix:
            lines.append(f"   Acción: {_telegram_safe(prefix)}")

    # Promedio de tareas exitosas (solo las mostradas)
    success_rows = [r for r in filtered if isinstance(r, dict) and (r.get("status") or "").upper() == "SUCCESS"]
    def _dur(r):
        try:
            return int(r.get("duration_ms") or 0)
        except (TypeError, ValueError):
            return 0
    avg_ms = sum(_dur(r) for r in success_rows) / len(success_rows) if success_rows else 0
    lines.append(f"---\nPromedio de ejecución: {avg_ms/1000:.2f}s")

    # Fallidas últimas 24h
    try:
        r24 = db.query(
            f"""
            SELECT COUNT(*) as cnt FROM {_TASK_AUDIT_TABLE}
            WHERE tenant_id = '{tenant_s}' AND status = 'FAILED'
            AND created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
            """
        )
        rows24 = json.loads(r24) if isinstance(r24, str) else (r24 or [])
        failed_24h = rows24[0].get("cnt", 0) if rows24 else 0
    except Exception:
        failed_24h = 0
    lines.append(f"Tareas fallidas (últimas 24h): {failed_24h}")

    return _telegram_safe("\n".join(lines))

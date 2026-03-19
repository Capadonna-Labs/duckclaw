"""
WorkerFactory: build a LangGraph instance from a worker template.

Input: worker_id, db_path, optional telegram_chat_id, instance_name.
Output: Compiled LangGraph with persistent state, ready for events.
"""

from __future__ import annotations

import json
import logging
import os
import re

_log = logging.getLogger(__name__)
from pathlib import Path
from typing import Any, Optional

try:
    from langchain_core.runnables import RunnableConfig
except ImportError:
    RunnableConfig = Any  # type: ignore[misc, assignment]

from duckclaw.workers.manifest import WorkerSpec, load_manifest, get_worker_dir
from duckclaw.workers.loader import load_system_prompt, load_skills, run_schema

_NO_TASK_PATTERN = re.compile(
    r"^(hola|hi|hey|buenos?\s*d[ií]as?|buenas?\s*tardes?|buenas?\s*noches?|"
    r"qu[eé]\s*tal|qu[eé]\s*hay|saludos?|hello|ciao|adios?|chao)\s*[!.]?$",
    re.IGNORECASE,
)

# Preguntas sobre DB/tablas/esquema son siempre tarea concreta (evitar "¿Cuál es mi tarea?")
_CONCRETE_TASK_KEYWORDS = re.compile(
    r"\b(db|database|base\s+de\s+datos|tablas?|tables?|esquema|schema|nombre\s+de\s+la\s+db|"
    r"qu[eé]\s+tablas|estructura|get_db_path|read_sql|admin_sql|consultar|cuenta|saldo|portfolio)\b",
    re.IGNORECASE,
)

# Tarea explícita del manager (plan): nunca tratar como "sin tarea"
_PLANNED_TASK_PREFIX = (
    "TAREA:",
    "TAREA ",
    "Ejecuta la herramienta",
    "Ejecuta read_sql",
    "Ejecuta admin_sql",
    "Usa read_sql",
    "Usa admin_sql",
    "usa get_db_path",
)


def _is_no_task(incoming: str) -> bool:
    """True si el mensaje está vacío o es solo un saludo genérico (sin tarea concreta)."""
    text = (incoming or "").strip()
    if not text:
        return True
    if len(text) < 4:
        return True
    # Tarea planificada por el manager (instrucción explícita)
    if any(text.startswith(p) or p in text for p in _PLANNED_TASK_PREFIX):
        return False
    # Preguntas sobre db/tablas/esquema/nombre son tarea concreta
    if _CONCRETE_TASK_KEYWORDS.search(text):
        return False
    return bool(_NO_TASK_PATTERN.match(text))


_TASK_AWARENESS_PROMPT = """
Además:
- Si no recibes una tarea concreta (mensaje vacío o solo saludos), pregunta: "¿Cuál es mi tarea?" y ofrece ejemplos de lo que puedes hacer según tu rol.
- En tu cierre proactivo invita a usar fly commands: si hablaste de datos o ejecución sugiere /tasks o /team; invita a crear objetivos con /goals (por defecto están vacíos); si de configuración /prompt o /skills; en general /help para ver todos los comandos.
"""


def _get_db_path(worker_id: str, instance_name: Optional[str], base_path: Optional[str]) -> str:
    """Resolve DuckDB path for this worker instance."""
    base = (base_path or os.environ.get("DUCKCLAW_DB_PATH") or "").strip()
    if not base:
        base = str(Path.cwd() / "db" / "workers.duckdb")
    p = Path(base)
    # Multi-vault: si ya recibimos una ruta explícita a un archivo .duckdb (p. ej. db/private/<user>/x.duckdb),
    # respetarla tal cual y no reescribir a workers_<instance>.duckdb.
    if base_path and p.suffix.lower() == ".duckdb":
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)
    if not p.suffix or p.suffix.lower() != ".duckdb":
        p = p / "workers.duckdb"
    # Optionally isolate per instance: db/workers_<instance>.duckdb
    if instance_name:
        p = p.parent / f"workers_{instance_name}.duckdb"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _identity_fields(state: dict) -> dict:
    return {
        "chat_id": state.get("chat_id") or state.get("session_id"),
        "tenant_id": state.get("tenant_id") or "default",
        "user_id": state.get("user_id") or "",
        "vault_db_path": state.get("vault_db_path") or "",
    }


def _build_worker_tools(db: Any, spec: WorkerSpec) -> list:
    """Build tool list: template skills + read/admin SQL (with allow-list)."""
    from langchain_core.tools import StructuredTool

    tools = load_skills(spec, db)
    schema = spec.schema_name

    # TimeContextSkill: si el manifest declara get_current_time o time_context, añadir la tool
    skills_list = getattr(spec, "skills_list", None) or []
    if "get_current_time" in skills_list or "time_context" in skills_list:
        try:
            from duckclaw.forge.skills.time_context import get_current_time
            tools.append(get_current_time)
        except Exception:
            pass

    def _enforce_allowed_tables(q_upper: str) -> Optional[json]:
        """Allow-list validation for queries touching DB tables."""
        if not spec.allowed_tables:
            return None
        # Permitir siempre information_schema (SHOW TABLES, esquema, etc.)
        if "INFORMATION_SCHEMA" in q_upper or "SHOW TABLES" in q_upper or "SHOW " in q_upper:
            return None
        for t in spec.allowed_tables:
            if t.upper() in q_upper or f"{schema}.{t}".upper() in q_upper:
                return None
        # No allowed table mentioned; check if query likely touches tables.
        if any(k in q_upper for k in ("FROM", "INTO", "UPDATE", "DELETE", "JOIN", "TABLE")):
            return json.dumps({"error": f"Solo se permiten las tablas: {', '.join(spec.allowed_tables)}."})
        return None

    def _read_sql_worker(query: str) -> str:
        if not query or not query.strip():
            return json.dumps({"error": "Query vacío."})
        q = query.strip()
        upper = q.upper()
        allowed_tables_error = _enforce_allowed_tables(upper)
        if allowed_tables_error:
            return allowed_tables_error
        # Bloquear escrituras (read_sql es solo lectura).
        if not upper.startswith(("SELECT", "WITH", "SHOW", "DESCRIBE", "EXPLAIN", "PRAGMA")):
            return json.dumps({"error": "read_sql es solo lectura. Usa admin_sql para escrituras (INSERT/UPDATE/DELETE/CREATE, etc.)."})
        try:
            # Siempre usamos query() para lecturas
            return db.query(q)
        except Exception as e:
            return json.dumps({"error": str(e)})

    tools.append(
        StructuredTool.from_function(
            _read_sql_worker,
            name="read_sql",
            description="Solo lectura SQL. SELECT/WITH/SHOW/DESCRIBE/EXPLAIN/PRAGMA. Restringe a tablas permitidas del worker.",
        )
    )

    def _admin_sql_worker(query: str) -> str:
        if not query or not query.strip():
            return json.dumps({"error": "Query vacío."})
        q = query.strip()
        upper = q.upper()

        allowed_tables_error = _enforce_allowed_tables(upper)
        if allowed_tables_error:
            return allowed_tables_error

        # Respetar read_only del worker para operaciones destructivas/escrituras.
        if spec.read_only and any(
            kw in upper
            for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE")
        ):
            return json.dumps({"error": "Este trabajador es solo lectura. No se permiten escrituras."})

        try:
            # Para cualquier query de lectura, usar query()
            if upper.startswith(("SELECT", "WITH", "SHOW", "DESCRIBE", "EXPLAIN", "PRAGMA")):
                return db.query(q)

            # Para escrituras, usar execute()
            db.execute(q)
            return json.dumps({"status": "ok"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    tools.append(
        StructuredTool.from_function(
            _admin_sql_worker,
            name="admin_sql",
            description="SQL con permisos admin: lectura + escrituras (INSERT/UPDATE/DELETE/CREATE/ALTER/DROP si el worker no es read_only). Respeta allow-list de tablas del worker si aplica.",
        )
    )

    def _inspect_schema_worker() -> str:
        """Lista tablas de todos los esquemas (main, finance_worker, etc.)."""
        try:
            r = json.loads(db.query(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema','pg_catalog') ORDER BY table_schema, table_name"
            ))
            if not r or not isinstance(r, list):
                return "No hay tablas en la base de datos."
            lines = []
            for row in r:
                sch = row.get("table_schema", "")
                tbl = row.get("table_name", "")
                if sch and tbl:
                    lines.append(f"- {sch}.{tbl}")
            return "Tablas disponibles:\n" + "\n".join(lines) if lines else "No hay tablas."
        except Exception as e:
            return json.dumps({"error": str(e)})

    tools.append(
        StructuredTool.from_function(
            _inspect_schema_worker,
            name="inspect_schema",
            description="Lista las tablas disponibles en la base de datos. Usar para preguntas sobre tablas, esquema o estructura.",
        )
    )

    from duckclaw.graphs.tools import get_db_path as _get_db_path_tool

    def _get_db_path_worker() -> str:
        return _get_db_path_tool(db)

    tools.append(
        StructuredTool.from_function(
            _get_db_path_worker,
            name="get_db_path",
            description="Devuelve la ruta o nombre del archivo .duckdb al que tiene acceso el agente. Usar cuando pregunten por el nombre de la base de datos.",
        )
    )
    return tools


def filter_tools_for_sandbox(tools: list[Any], enabled: bool) -> list[Any]:
    """
    Helper (unit-testable): si sandbox está OFF, elimina la herramienta `run_sandbox`.
    """
    if enabled:
        return list(tools)
    return [t for t in tools if getattr(t, "name", "") != "run_sandbox"]


class WorkerFactory:
    """Factory for Virtual Workers (template-based LangGraph agents)."""

    def __init__(self, templates_root: Optional[Path] = None):
        self.templates_root = templates_root

    def create(
        self,
        worker_id: str,
        db_path: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        instance_name: Optional[str] = None,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_base_url: Optional[str] = None,
    ) -> Any:
        """
        Build and return a compiled LangGraph for the worker.
        Shim: delega a build_worker_graph (compatible con AgentAssembler).
        """
        return build_worker_graph(
            worker_id,
            db_path,
            None,
            templates_root=self.templates_root,
            instance_name=instance_name,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_base_url=llm_base_url,
        )


def build_worker_graph(
    worker_id: str,
    db_path: Optional[str],
    llm: Optional[Any],
    *,
    templates_root: Optional[Path] = None,
    instance_name: Optional[str] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_base_url: Optional[str] = None,
) -> Any:
    """
    Build a compiled LangGraph for a worker. Used by AgentAssembler._build_worker
    and by WorkerFactory.create() (shim).
    """
    spec = load_manifest(worker_id, templates_root)
    path = _get_db_path(worker_id, instance_name, db_path)

    from duckclaw import DuckClaw
    db = DuckClaw(path)
    # Multi-vault: exponer siempre la bóveda activa bajo alias SQL `private`.
    # Es best-effort para no romper workers existentes.
    try:
        escaped_path = str(path).replace("'", "''")
        try:
            db.execute("DETACH private")
        except Exception:
            pass
        db.execute(f"ATTACH '{escaped_path}' AS private")
    except Exception:
        pass
    run_schema(db, spec)

    system_prompt = load_system_prompt(spec)
    tools = _build_worker_tools(db, spec)
    if getattr(spec, "github_config", None):
        try:
            from duckclaw.forge.skills.github_bridge import register_github_skill
            register_github_skill(tools, spec.github_config)
        except Exception:
            pass
    tools_by_name = {t.name: t for t in tools}

    # Inferencia Elástica (Hardware-Aware): si el manifest tiene inference y no se pasó provider/model/base_url explícito, detectar hardware
    inference_config = getattr(spec, "inference_config", None)
    if inference_config is not None and not llm_provider and not llm_model and not llm_base_url:
        try:
            from duckclaw.integrations.hardware_detector import (
                get_inference_config,
                resolve_llm_params_from_config,
            )
            config = get_inference_config(inference_config)
            provider, model, base_url = resolve_llm_params_from_config(config)
            provider = (provider or "none_llm").strip().lower()
            model = (model or "").strip()
            base_url = (base_url or "").strip()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Hardware detection failed or fallback disabled: %s", e)
            provider = "none_llm"
            model = ""
            base_url = ""
    else:
        provider = (llm_provider or os.environ.get("DUCKCLAW_LLM_PROVIDER") or "none_llm").strip().lower()
        model = (llm_model or os.environ.get("DUCKCLAW_LLM_MODEL") or "").strip()
        base_url = (llm_base_url or os.environ.get("DUCKCLAW_LLM_BASE_URL") or "").strip()

    if llm is None and provider != "none_llm":
        from duckclaw.integrations.llm_providers import build_llm
        llm = build_llm(provider, model, base_url)
    elif llm is None:
        llm = None

    if getattr(spec, "research_config", None):
        try:
            from duckclaw.forge.skills.research_bridge import register_research_skill
            register_research_skill(tools, spec.research_config, llm=llm)
            tools_by_name = {t.name: t for t in tools}
        except Exception:
            pass

    if getattr(spec, "tailscale_config", None):
        try:
            from duckclaw.forge.skills.tailscale_bridge import register_tailscale_skill
            register_tailscale_skill(tools, spec.tailscale_config)
            tools_by_name = {t.name: t for t in tools}
        except Exception:
            pass

    if getattr(spec, "ibkr_config", None) is not None:
        try:
            from duckclaw.forge.skills.ibkr_bridge import register_ibkr_skill
            register_ibkr_skill(tools, spec.ibkr_config)
            tools_by_name = {t.name: t for t in tools}
        except Exception:
            pass

    if getattr(spec, "sft_config", None):
        try:
            from duckclaw.forge.skills.sft_bridge import register_sft_skill
            register_sft_skill(tools, spec.sft_config)
            tools_by_name = {t.name: t for t in tools}
        except Exception:
            pass

    if getattr(spec, "homeostasis_config", None):
        try:
            from duckclaw.forge.skills.homeostasis_bridge import register_homeostasis_skill
            register_homeostasis_skill(tools, spec, db, tools_by_name)
            tools_by_name = {t.name: t for t in tools}
        except Exception:
            pass

    # Strix Sandbox: solo agregar `run_sandbox` si el worker define policy.
    try:
        security_policy_path = spec.worker_dir / "security_policy.yaml"
        if security_policy_path.is_file() and llm is not None and "run_sandbox" not in tools_by_name:
            from duckclaw.graphs.sandbox import sandbox_tool_factory

            tools.append(sandbox_tool_factory(db, llm))
            tools_by_name = {t.name: t for t in tools}
    except Exception:
        pass

    # Aplicar LangSmith config al grafo final (no solo al llm) si está habilitado
    send_to_langsmith = os.environ.get("DUCKCLAW_SEND_TO_LANGSMITH", "false").lower() == "true"
    if send_to_langsmith:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        # Honor explicitly set project in env, otherwise fallback to spec name or default
        if not os.environ.get("LANGCHAIN_PROJECT"):
            os.environ["LANGCHAIN_PROJECT"] = instance_name or getattr(spec, "name", "DuckClaw") or "default"
        # Si la API KEY no existe en el entorno, LangSmith simplemente la ignorará o fallará silenciosamente
    else:
        # Desactivar explícitamente para esta instanciación si estaba globalmente activo
        os.environ["LANGCHAIN_TRACING_V2"] = "false"

    from langgraph.graph import END, StateGraph
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

    has_homeostasis = bool(getattr(spec, "homeostasis_config", None))
    crm_config = getattr(spec, "crm_config", None) or {}
    crm_enabled = bool(crm_config.get("enabled", False))
    effective_prompt = (system_prompt or "").strip() + "\n\n" + _TASK_AWARENESS_PROMPT.strip()

    def prepare_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        cfg = config or {}
        conf_obj = cfg.get("configurable")
        meta = cfg.get("metadata") or {}
        conf_incoming = (conf_obj.get("incoming") if isinstance(conf_obj, dict) else None) or (meta.get("incoming") if meta else None)
        incoming = (
            (state.get("incoming") or state.get("input") or "").strip()
            or (str(conf_incoming).strip() if conf_incoming else "")
        )
        if not incoming and state.get("messages"):
            for m in reversed(state["messages"]):
                if isinstance(m, HumanMessage) and getattr(m, "content", None):
                    incoming = (str(m.content) or "").strip()
                    break
        if not isinstance(incoming, str):
            incoming = str(incoming or "").strip()
        prompt = effective_prompt
        if crm_enabled:
            try:
                from duckclaw.forge.crm.context_injector import graph_context_injector
                lead_id = state.get("chat_id") or state.get("session_id") or "default"
                lead_ctx = graph_context_injector(db, lead_id)
                if lead_ctx:
                    prompt = prompt + "\n\n<lead_context>\n" + lead_ctx + "\n</lead_context>"
            except Exception:
                pass
        messages = [SystemMessage(content=prompt)]
        for h in (state.get("history") or []):
            role = (h.get("role") or "").lower()
            content = h.get("content") or ""
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        needs_task = state.get("homeostasis_hint") == "ask_task" or _is_no_task(incoming)
        if needs_task:
            user_content = (
                f"[El usuario dijo: '{incoming.strip() or '(vacío)'}'. No ha indicado una tarea concreta. "
                "Pregúntale: ¿Cuál es mi tarea? Y ofrece ejemplos de lo que puedes hacer según tu rol.]"
            )
        else:
            user_content = incoming
        messages.append(HumanMessage(content=user_content))
        # LangGraph puede reemplazar/limitar el state entre nodos; preservamos chat_id para
        # que _sandbox_enabled_for_state (y otros flags por sesión) lean el ID correcto.
        out = {"messages": messages, "incoming": incoming}
        out.update(_identity_fields(state))
        return out

    def _sandbox_enabled_for_state(state: dict) -> bool:
        """Sandbox flag per chat/session (defaults to OFF)."""
        from duckclaw.graphs.on_the_fly_commands import get_chat_state

        chat_id = state.get("chat_id") or state.get("session_id") or "default"
        raw = get_chat_state(db, chat_id, "sandbox_enabled")
        v = (raw or "").strip().lower()
        enabled = v in ("true", "1", "on", "sí", "si")
        # Use warning so it always shows up in pm2 logs even if INFO is filtered.
        db_path = getattr(db, "_path", None) or getattr(db, "path", None) or "(unknown_db_path)"
        _log.warning("[sandbox] db_path=%r chat_id=%r sandbox_enabled_raw=%r enabled=%s", db_path, chat_id, raw, enabled)
        return enabled

    tools_sandbox_off = filter_tools_for_sandbox(tools, enabled=False)
    tools_by_name_sandbox_off = {t.name: t for t in tools_sandbox_off}

    if llm is None:
        def agent_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
            out = {"messages": state["messages"] + [AIMessage(content="Sin LLM configurado. Configura DUCKCLAW_LLM_PROVIDER.")]}
            out.update(_identity_fields(state))
            return out
    else:
        # Cache de re-ligado por modo (evita re-bind costoso por chat/turno).
        llm_with_tools_on = llm.bind_tools(tools)
        llm_with_tools_off = llm.bind_tools(tools_sandbox_off)

        has_ibkr = "get_ibkr_portfolio" in tools_by_name
        tool_choice_inspect_schema = {"type": "function", "function": {"name": "inspect_schema"}}
        tool_choice_portfolio = {"type": "function", "function": {"name": "get_ibkr_portfolio"}}

        llm_force_schema_on = llm.bind_tools(tools, tool_choice=tool_choice_inspect_schema)
        llm_force_schema_off = llm.bind_tools(tools_sandbox_off, tool_choice=tool_choice_inspect_schema)
        llm_force_portfolio_on = llm.bind_tools(tools, tool_choice=tool_choice_portfolio) if has_ibkr else None
        llm_force_portfolio_off = (
            llm.bind_tools(tools_sandbox_off, tool_choice=tool_choice_portfolio) if has_ibkr else None
        )

        def _is_portfolio_query(text: str) -> bool:
            if not text or not text.strip():
                return False
            t = text.strip().lower()
            # Excluir: gastos/transacciones locales (evitar que "acciones" en "transacciones" dispare IBKR)
            if any(k in t for k in ("transacciones", "gastos", "compras", "presupuesto")):
                return False
            # Excluir: tablas DuckDB, esquema o estructura de base de datos
            if any(k in t for k in ("tablas", "tabla", "duckdb", "esquema", "schema", "estructura", "qué tablas", "que tablas")):
                return False
            # Excluir: cuenta bancaria concreta (Bancolombia, etc.) -> debe usar read_sql/admin_sql sobre .duckdb
            if any(k in t for k in ("cuenta de ", "cuenta bancolombia", "bancolombia", "en bancolombia", "saldo en mi cuenta")):
                return False
            # "Portfolio total" / "cuánto tengo en total" -> no forzar solo IBKR; el agente debe usar get_ibkr_portfolio + read_sql (cuentas en .duckdb)
            if any(k in t for k in ("portfolio total", "en total", "resumen de todo", "cuánto tengo en total", "cuanto tengo en total")):
                return False
            # "acciones" como palabra completa (no subcadena de "transacciones")
            # "ibkr", "en ibkr" -> consultas explícitas al broker
            kw = ("portfolio", "portafolio", "cuanto dinero", "cuánto dinero", "saldo ibkr", "dinero en bolsa", "resumen de mi portfolio", "estado de mis cuentas", "estado de cuenta", "mis cuentas", "en ibkr", "ibkr", "interactive brokers")
            if any(k in t for k in kw):
                return True
            return bool(re.search(r"\bacciones\b", t))

        def _is_schema_query(text: str) -> bool:
            if not text or not text.strip():
                return False
            t = text.strip().lower()
            return any(k in t for k in ("tablas", "tabla", "duckdb", "esquema", "schema", "estructura", "qué tablas", "que tablas"))

        def agent_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
            cfg = config or {}
            incoming = (
                (state.get("incoming") or state.get("input") or "").strip()
                or (cfg.get("configurable") or {}).get("incoming") or ""
            )
            if isinstance(incoming, str):
                incoming = incoming.strip()
            else:
                incoming = str(incoming or "").strip()
            # Fallback: extraer del último HumanMessage
            if not incoming and state.get("messages"):
                for m in reversed(state["messages"]):
                    if isinstance(m, HumanMessage) and getattr(m, "content", None):
                        incoming = (str(m.content) or "").strip()
                        break
            is_schema = _is_schema_query(incoming)
            is_portfolio = has_ibkr and _is_portfolio_query(incoming)
            # No forzar herramienta si el último mensaje ya es ToolMessage (ya ejecutamos la tool):
            # así el LLM puede responder con texto y no entrar en bucle (inspect_schema -> agent -> inspect_schema).
            last_msg = (state.get("messages") or [])[-1] if state.get("messages") else None
            already_has_tool_result = last_msg is not None and isinstance(last_msg, ToolMessage)
            force_schema = is_schema and not already_has_tool_result
            force_portfolio = is_portfolio and not already_has_tool_result

            sandbox_enabled = _sandbox_enabled_for_state(state)
            llm_with_tools = llm_with_tools_on if sandbox_enabled else llm_with_tools_off
            _log.info(
                "[finanz] incoming=%r | is_schema=%s | is_portfolio=%s | forced_tool=%s",
                incoming[:80] + ("..." if len(incoming) > 80 else ""),
                is_schema,
                is_portfolio,
                "inspect_schema" if force_schema else ("get_ibkr_portfolio" if force_portfolio else "auto"),
            )
            if force_schema:
                resp = (llm_force_schema_on if sandbox_enabled else llm_force_schema_off).invoke(state["messages"])
            elif force_portfolio:
                forced = llm_force_portfolio_on if sandbox_enabled else llm_force_portfolio_off
                # has_ibkr => forced should not be None
                resp = (forced or llm_with_tools).invoke(state["messages"])
            else:
                resp = llm_with_tools.invoke(state["messages"])
            tool_calls = getattr(resp, "tool_calls", None) or []
            if tool_calls:
                _log.info("[finanz] LLM tool_calls=%s", [tc.get("name") for tc in tool_calls])
            out = {"messages": state["messages"] + [resp]}
            out.update(_identity_fields(state))
            return out

    def tools_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        messages = state["messages"]
        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        new_msgs = list(messages)
        sandbox_enabled = _sandbox_enabled_for_state(state)
        tool_lookup = tools_by_name if sandbox_enabled else tools_by_name_sandbox_off
        for tc in tool_calls:
            name = (tc.get("name") or "").strip()
            args = tc.get("args") or {}
            tid = tc.get("id") or ""
            tool = tool_lookup.get(name)
            if tool:
                try:
                    result = tool.invoke(args)
                    content = str(result) if result is not None else "OK"
                    _log.info("[finanz] tool=%s | result_len=%d | preview=%r", name, len(content), content[:120] + ("..." if len(content) > 120 else ""))
                except Exception as e:
                    content = f"Error: {e}"
                    _log.warning("[finanz] tool=%s failed: %s", name, e)
            else:
                if not sandbox_enabled and name == "run_sandbox":
                    content = "Sandbox deshabilitado en esta sesión. Actívalo con /sandbox on."
                else:
                    content = f"Herramienta desconocida: {name}"
                _log.warning("[finanz] unknown/unavailable tool: %s (sandbox_enabled=%s)", name, sandbox_enabled)
            new_msgs.append(ToolMessage(content=content, tool_call_id=tid, name=name))
        out = {"messages": new_msgs}
        out.update(_identity_fields(state))
        return out

    def set_reply(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        from duckclaw.integrations.llm_providers import _strip_eot
        msgs = state.get("messages") or []
        last = msgs[-1] if msgs else None
        reply = getattr(last, "content", None) or str(last) if last else ""
        reply = _strip_eot(reply or "").strip()
        if not msgs:
            return {"reply": "Sin respuesta generada."}
        if reply.startswith("{") and '"name"' in reply and ("parameters" in reply or '"args"' in reply):
            try:
                from duckclaw.utils import format_tool_reply
                data = json.loads(reply)
                name = data.get("name") or data.get("tool")
                params = data.get("parameters") or data.get("args") or {}
                sandbox_enabled = _sandbox_enabled_for_state(state)
                tool_lookup = tools_by_name if sandbox_enabled else tools_by_name_sandbox_off
                if name and name in tool_lookup:
                    result = tool_lookup[name].invoke(params)
                    text = str(result) if result else "Listo."
                    return {"reply": format_tool_reply(text), "messages": msgs}
            except (json.JSONDecodeError, TypeError, KeyError, Exception):
                pass
        out = {"reply": reply or "", "messages": msgs}
        out.update(_identity_fields(state))
        return out

    def should_continue(state: dict) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else "end"

    # Context-Guard (FactChecker + SelfCorrection) para workers con catalog_retriever
    context_guard_config = getattr(spec, "context_guard_config", None) or {}
    context_guard_enabled = (
        bool(context_guard_config.get("enabled", False))
        and "catalog_retriever" in (spec.skills_list or [])
    )
    max_retries = int(context_guard_config.get("max_retries", 2))

    def fact_check_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        from duckclaw.forge.atoms.validators import fact_checker_node as _fc
        return _fc(state, llm, max_retries=max_retries)

    def self_correction_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        from duckclaw.forge.atoms.validators import self_correction_node as _sc
        return _sc(state, llm)

    def handoff_reply_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        from duckclaw.forge.atoms.validators import handoff_reply_node as _hr
        return _hr(state)

    def route_after_fact_check(state: dict) -> str:
        return state.get("context_guard_route", "approved")

    def homeostasis_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        """HomeostasisNode: Percepción-Sorpresa-Restauración-Actualización. Fase 1: pass-through (tabla ya creada en run_schema).
        IMPORTANTE: retornar state para preservar input/incoming; retornar {} vacío hace que LangGraph pierda el estado."""
        return state

    graph = StateGraph(dict)
    graph.add_node("prepare", prepare_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("set_reply", set_reply)
    if context_guard_enabled:
        graph.add_node("fact_check", fact_check_node)
        graph.add_node("self_correction", self_correction_node)
        graph.add_node("handoff_reply", handoff_reply_node)
    if getattr(spec, "homeostasis_config", None):
        graph.add_node("homeostasis", homeostasis_node)
        graph.set_entry_point("homeostasis")
        graph.add_edge("homeostasis", "prepare")
    else:
        graph.set_entry_point("prepare")
    graph.add_edge("prepare", "agent")
    if context_guard_enabled:
        graph.add_conditional_edges(
            "agent", should_continue,
            {"tools": "tools", "end": "fact_check"},
        )
        graph.add_conditional_edges(
            "fact_check", route_after_fact_check,
            {"approved": "set_reply", "correct": "self_correction", "handoff": "handoff_reply"},
        )
        graph.add_edge("self_correction", "fact_check")
        graph.add_edge("handoff_reply", END)
    else:
        graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": "set_reply"})
    graph.add_edge("tools", "agent")
    graph.add_edge("set_reply", END)

    compiled = graph.compile()
    compiled._worker_spec = spec
    compiled._worker_db = db
    return compiled


def list_workers(templates_root: Optional[Path] = None) -> list[str]:
    """Return worker_id for each template in templates/workers/."""
    if templates_root is not None:
        workers_dir = templates_root / "templates" / "workers"
    else:
        try:
            from duckclaw.forge import WORKERS_TEMPLATES_DIR
            workers_dir = WORKERS_TEMPLATES_DIR
        except ImportError:
            # packages/agents/src/duckclaw/workers -> packages/agents
            root = Path(__file__).resolve().parent.parent.parent.parent
            workers_dir = root / "templates" / "workers"
    if not workers_dir.is_dir():
        return []
    return [d.name for d in workers_dir.iterdir() if d.is_dir() and (d / "manifest.yaml").is_file()]

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


def _get_db_path(worker_id: str, instance_name: Optional[str], base_path: Optional[str]) -> str:
    """Resolve DuckDB path for this worker instance."""
    base = (base_path or os.environ.get("DUCKCLAW_DB_PATH") or "").strip()
    if not base:
        base = str(Path.cwd() / "db" / "workers.duckdb")
    p = Path(base)
    if not p.suffix or p.suffix.lower() != ".duckdb":
        p = p / "workers.duckdb"
    # Optionally isolate per instance: db/workers_<instance>.duckdb
    if instance_name:
        p = p.parent / f"workers_{instance_name}.duckdb"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _build_worker_tools(db: Any, spec: WorkerSpec) -> list:
    """Build tool list: template skills + optional run_sql with allow-list."""
    from langchain_core.tools import StructuredTool

    tools = load_skills(spec, db)
    schema = spec.schema_name

    def _run_sql_worker(query: str) -> str:
        if not query or not query.strip():
            return json.dumps({"error": "Query vacío."})
        q = query.strip()
        if spec.read_only:
            if any(kw in q.upper() for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER")):
                return json.dumps({"error": "Este trabajador es solo lectura. No se permiten escrituras."})
        if spec.allowed_tables:
            # Allow-list: only these tables (optionally schema-qualified)
            # Permitir siempre information_schema (SHOW TABLES, esquema, etc.)
            upper = q.upper()
            if "INFORMATION_SCHEMA" in upper or "SHOW TABLES" in upper or "SHOW " in upper:
                pass  # skip allow-list
            else:
                for t in spec.allowed_tables:
                    if t.upper() in upper or f"{schema}.{t}".upper() in upper:
                        break
                else:
                    # No allowed table mentioned; check if query touches any table
                    if "FROM" in upper or "INTO" in upper or "UPDATE" in upper or "JOIN" in upper:
                        return json.dumps({
                            "error": f"Solo se permiten las tablas: {', '.join(spec.allowed_tables)}."
                        })
        try:
            if q.upper().startswith(("SELECT", "WITH", "SHOW", "DESCRIBE")):
                return db.query(q)
            db.execute(q)
            return json.dumps({"status": "ok"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    tools.append(
        StructuredTool.from_function(
            _run_sql_worker,
            name="run_sql",
            description="Ejecuta SQL en el esquema del trabajador. Respeta restricciones de tablas permitidas.",
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
    return tools


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

    def prepare_node(state: dict, config: RunnableConfig | None = None) -> dict:
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
        messages = [SystemMessage(content=system_prompt)]
        for h in (state.get("history") or []):
            role = (h.get("role") or "").lower()
            content = h.get("content") or ""
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        messages.append(HumanMessage(content=incoming))
        return {"messages": messages, "incoming": incoming}

    if llm is None:
        def agent_node(state: dict) -> dict:
            return {"messages": state["messages"] + [AIMessage(content="Sin LLM configurado. Configura DUCKCLAW_LLM_PROVIDER.")]}
    else:
        llm_with_tools = llm.bind_tools(tools)
        has_ibkr = "get_ibkr_portfolio" in tools_by_name

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
            # "acciones" como palabra completa (no subcadena de "transacciones")
            kw = ("portfolio", "portafolio", "cuanto dinero", "cuánto dinero", "saldo ibkr", "dinero en bolsa", "resumen de mi portfolio", "estado de mis cuentas", "estado de cuenta", "mis cuentas")
            if any(k in t for k in kw):
                return True
            return bool(re.search(r"\bacciones\b", t))

        def _is_schema_query(text: str) -> bool:
            if not text or not text.strip():
                return False
            t = text.strip().lower()
            return any(k in t for k in ("tablas", "tabla", "duckdb", "esquema", "schema", "estructura", "qué tablas", "que tablas"))

        def agent_node(state: dict, config: RunnableConfig | None = None) -> dict:
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
            _log.info(
                "[finanz] incoming=%r | is_schema=%s | is_portfolio=%s | forced_tool=%s",
                incoming[:80] + ("..." if len(incoming) > 80 else ""),
                is_schema,
                is_portfolio,
                "inspect_schema" if is_schema else ("get_ibkr_portfolio" if is_portfolio else "auto"),
            )
            if is_schema:
                llm_forced = llm.bind_tools(tools, tool_choice={"type": "function", "function": {"name": "inspect_schema"}})
                resp = llm_forced.invoke(state["messages"])
            elif is_portfolio:
                llm_forced = llm.bind_tools(tools, tool_choice={"type": "function", "function": {"name": "get_ibkr_portfolio"}})
                resp = llm_forced.invoke(state["messages"])
            else:
                resp = llm_with_tools.invoke(state["messages"])
            tool_calls = getattr(resp, "tool_calls", None) or []
            if tool_calls:
                _log.info("[finanz] LLM tool_calls=%s", [tc.get("name") for tc in tool_calls])
            return {"messages": state["messages"] + [resp]}

    def tools_node(state: dict) -> dict:
        messages = state["messages"]
        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        new_msgs = list(messages)
        for tc in tool_calls:
            name = (tc.get("name") or "").strip()
            args = tc.get("args") or {}
            tid = tc.get("id") or ""
            tool = tools_by_name.get(name)
            if tool:
                try:
                    result = tool.invoke(args)
                    content = str(result) if result is not None else "OK"
                    _log.info("[finanz] tool=%s | result_len=%d | preview=%r", name, len(content), content[:120] + ("..." if len(content) > 120 else ""))
                except Exception as e:
                    content = f"Error: {e}"
                    _log.warning("[finanz] tool=%s failed: %s", name, e)
            else:
                content = f"Herramienta desconocida: {name}"
                _log.warning("[finanz] unknown tool: %s", name)
            new_msgs.append(ToolMessage(content=content, tool_call_id=tid))
        return {"messages": new_msgs}

    def set_reply(state: dict) -> dict:
        from duckclaw.integrations.llm_providers import _strip_eot
        msgs = state["messages"]
        last = msgs[-1]
        reply = getattr(last, "content", None) or str(last)
        reply = _strip_eot(reply or "").strip()
        if reply.startswith("{") and '"name"' in reply and ("parameters" in reply or '"args"' in reply):
            try:
                from duckclaw.utils import format_tool_reply
                data = json.loads(reply)
                name = data.get("name") or data.get("tool")
                params = data.get("parameters") or data.get("args") or {}
                if name and name in tools_by_name:
                    result = tools_by_name[name].invoke(params)
                    text = str(result) if result else "Listo."
                    return {"reply": format_tool_reply(text)}
            except (json.JSONDecodeError, TypeError, KeyError, Exception):
                pass
        return {"reply": reply or ""}

    def should_continue(state: dict) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else "end"

    def homeostasis_node(state: dict) -> dict:
        """HomeostasisNode: Percepción-Sorpresa-Restauración-Actualización. Fase 1: pass-through (tabla ya creada en run_schema).
        IMPORTANTE: retornar state para preservar input/incoming; retornar {} vacío hace que LangGraph pierda el estado."""
        return state

    graph = StateGraph(dict)
    graph.add_node("prepare", prepare_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("set_reply", set_reply)
    if getattr(spec, "homeostasis_config", None):
        graph.add_node("homeostasis", homeostasis_node)
        graph.set_entry_point("homeostasis")
        graph.add_edge("homeostasis", "prepare")
    else:
        graph.set_entry_point("prepare")
    graph.add_edge("prepare", "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": "set_reply"})
    graph.add_edge("tools", "agent")
    graph.add_edge("set_reply", END)

    compiled = graph.compile()
    compiled._worker_spec = spec
    compiled._worker_db = db
    return compiled


def list_workers(templates_root: Optional[Path] = None) -> list[str]:
    """Return worker_id for each template in templates/workers/."""
    root = templates_root or Path(__file__).resolve().parent.parent.parent
    workers_dir = root / "templates" / "workers"
    if not workers_dir.is_dir():
        return []
    return [d.name for d in workers_dir.iterdir() if d.is_dir() and (d / "manifest.yaml").is_file()]

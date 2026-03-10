"""
WorkerFactory: build a LangGraph instance from a worker template.

Input: worker_id, db_path, optional telegram_chat_id, instance_name.
Output: Compiled LangGraph with persistent state, ready for events.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from duckclaw.workers.manifest import WorkerSpec, load_manifest, get_worker_dir
from duckclaw.workers.loader import load_system_prompt, load_skills, run_schema

# Patrones que indican ausencia de tarea concreta (saludos genéricos)
_NO_TASK_PATTERN = re.compile(
    r"^(hola|hi|hey|buenos?\s*d[ií]as?|buenas?\s*tardes?|buenas?\s*noches?|"
    r"qu[eé]\s*tal|qu[eé]\s*hay|saludos?|hello|ciao|adios?|chao)\s*[!.]?$",
    re.IGNORECASE,
)


def _is_no_task(incoming: str) -> bool:
    """True si el mensaje está vacío o es solo un saludo genérico (sin tarea concreta)."""
    text = (incoming or "").strip()
    if not text:
        return True
    if len(text) < 4:
        return True
    return bool(_NO_TASK_PATTERN.match(text))


_TASK_AWARENESS_PROMPT = """
Además:
- Si no recibes una tarea concreta (mensaje vacío o solo saludos), pregunta: "¿Cuál es mi tarea?" y ofrece ejemplos de lo que puedes hacer según tu rol.
- Mientras resuelves una tarea, al final sugiere 1-3 tareas similares que podrías hacer a continuación.
"""


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

    from duckclaw.security import SQLValidator

    tools = load_skills(spec, db)
    schema = spec.schema_name
    validator = SQLValidator(
        read_only=spec.read_only,
        allowed_tables=spec.allowed_tables or None,
        schema_name=schema,
    )

    def _run_sql_worker(query: str) -> str:
        if not query or not query.strip():
            return json.dumps({"error": "Query vacío."})
        q = query.strip()
        ok, err = validator.validate(q)
        if not ok:
            return json.dumps({"error": err})
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

    has_homeostasis = bool(getattr(spec, "homeostasis_config", None))
    effective_prompt = (system_prompt or "").strip() + "\n\n" + _TASK_AWARENESS_PROMPT.strip()

    def prepare_node(state: dict) -> dict:
        messages = [SystemMessage(content=effective_prompt)]
        for h in (state.get("history") or []):
            role = (h.get("role") or "").lower()
            content = h.get("content") or ""
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        incoming = state.get("incoming") or ""
        needs_task = state.get("homeostasis_hint") == "ask_task" or _is_no_task(incoming)
        if needs_task:
            user_content = (
                f"[El usuario dijo: '{incoming.strip() or '(vacío)'}'. No ha indicado una tarea concreta. "
                "Pregúntale: ¿Cuál es mi tarea? Y ofrece ejemplos de lo que puedes hacer según tu rol.]"
            )
        else:
            user_content = incoming
        messages.append(HumanMessage(content=user_content))
        return {"messages": messages}

    if llm is None:
        def agent_node(state: dict) -> dict:
            return {"messages": state["messages"] + [AIMessage(content="Sin LLM configurado. Configura DUCKCLAW_LLM_PROVIDER.")]}
    else:
        llm_with_tools = llm.bind_tools(tools)

        def agent_node(state: dict) -> dict:
            resp = llm_with_tools.invoke(state["messages"])
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
                except Exception as e:
                    content = f"Error: {e}"
            else:
                content = f"Herramienta desconocida: {name}"
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
        """HomeostasisNode: Percepción-Sorpresa-Restauración-Actualización.
        Detecta ausencia de tarea (incoming vacío o saludo genérico) y señala ask_task."""
        incoming = state.get("incoming") or ""
        if _is_no_task(incoming):
            return {"homeostasis_hint": "ask_task"}
        return {}

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

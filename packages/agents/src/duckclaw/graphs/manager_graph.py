"""
Manager graph: orquestador que asigna cada mensaje a un subagente (worker) y registra en /tasks y /history.

State: incoming, history, chat_id, reply, assigned_worker_id, planned_task, messages (opcional).
Flujo: router -> plan (formula tarea clara para el worker) -> invoke_worker (set_busy, invoca worker, set_idle, append_task_audit).
Spec: Plan manager orquestador de subagentes.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from duckclaw.forge.atoms.state import ManagerAgentState
from duckclaw.utils.langsmith_trace import get_tracing_config
from duckclaw.utils.logger import get_obs_logger, log_plan, log_sys, set_log_context

_log = logging.getLogger(__name__)
_obs = get_obs_logger()
_worker_graph_cache: dict[str, Any] = {}


def _plan_task(incoming: str, worker_id: str) -> tuple[str, Optional[str]]:
    """
    Convierte el mensaje del usuario en una tarea explícita para el subagente.
    Retorna (planned_task, override_worker_id).
    override_worker_id: si la intención es DB/tablas y el rol actual es personalizable, delegar a finanz si existe.
    """
    text = (incoming or "").strip()
    if not text:
        return incoming or "", None
    t = text.lower()
    override: Optional[str] = None
    # Intención DB/tablas/nombre → si el rol es personalizable, usar finanz (especialista) si está disponible
    is_db_intent = (
        re.search(r"\b(nombre\s+de\s+la\s+db|db|tablas?|tables?|esquema|schema|estructura|disponibles)\b", t)
        or "tablas" in t
        or ("nombre" in t and ("db" in t or "base" in t or "datos" in t))
    )
    if is_db_intent and (worker_id or "").strip().lower() == "personalizable":
        override = "finanz"  # invoke_worker lo usará si finanz está en list_workers

    # Nombre de la db / base de datos
    if re.search(r"\b(nombre\s+de\s+la\s+db|nombre\s+db|cual\s+es\s+el\s+nombre|nombre\s+de\s+la\s+base)\b", t) or (
        "nombre" in t and ("db" in t or "base" in t or "datos" in t)
    ):
        task = (
            "TAREA: El usuario quiere saber qué base de datos se está usando. "
            "Ejecuta get_db_path y responde de forma proactiva: indica la db usada en texto plano (sin comillas ni negrita). En el cierre invita a /team, /tasks, /help y a crear objetivos con /goals (por defecto están vacíos). Usa 1-2 emojis si encaja."
        )
        return task, override
    # Tablas / esquema / estructura
    if re.search(
        r"\b(tablas?|tables?|esquema|schema|estructura|listar\s+tablas|disponibles)\b",
        t,
    ) or "tablas" in t or "qué tablas" in t or "que tablas" in t:
        task = (
            "TAREA: El usuario quiere ver las tablas de la base de datos. "
            "Ejecuta read_sql con SHOW TABLES o SELECT desde information_schema.tables y responde con la lista de tablas. En el cierre invita a /team, /tasks, /help y a crear objetivos con /goals."
        )
        return task, override
    return text, override


def _llm_plan(incoming: str) -> tuple[str, list[str]]:
    """
    Planner ligero basado en heurísticas que emula la salida estructurada esperada:
    {
      "plan_title": string,
      "tasks": [string]
    }

    Nota: en esta primera versión no se invoca un LLM explícito; se estructura
    el plan de forma determinista a partir del mensaje, dejando el contrato y
    el estado preparados para una futura integración con LLM.
    """
    text = (incoming or "").strip()
    if not text:
        return "Interacción sin contenido", []

    lower = text.lower()
    if "saldo" in lower or "dinero" in lower or "cuenta" in lower:
        title = "Consulta de Saldo Total"
    elif "tabla" in lower or "tablas" in lower or "schema" in lower or "esquema" in lower:
        title = "Inspección de Esquema de DB"
    elif "hora" in lower or "fecha" in lower or "hoy" in lower:
        title = "Consulta de Contexto Temporal"
    else:
        # Fallback: primeras ~5 palabras como título
        words = text.split()
        title = " ".join(words[:5]) if words else "Interacción del Usuario"

    tasks: list[str] = [f"Resolver la solicitud del usuario: {text}"]
    return title, tasks


def _task_summary_for_activity(incoming: str, planned_task: str) -> str:
    """Resumen corto de la tarea para /tasks (activity), no el planned_task completo."""
    t = (incoming or "").strip().lower()
    pt = (planned_task or "").strip().lower()
    # Nombre de la db
    if re.search(r"\b(nombre\s+de\s+la\s+db|nombre\s+db|cual\s+es\s+el\s+nombre|nombre\s+de\s+la\s+base)\b", t) or (
        "nombre" in t and ("db" in t or "base" in t or "datos" in t)
    ) or "get_db_path" in pt and "nombre" in pt:
        return "Buscando el nombre de la db disponible."
    # Tablas / esquema
    if re.search(
        r"\b(tablas?|tables?|esquema|schema|estructura|listar\s+tablas|disponibles)\b",
        t,
    ) or "tablas" in t or "qué tablas" in t or "que tablas" in t or "show tables" in pt:
        return "Listando tablas de la base de datos."
    # Fallback: primeras palabras del mensaje del usuario (máx. ~50 caracteres)
    if incoming and len(incoming) > 48:
        return (incoming[:48] + "…").strip()
    return incoming or "Procesando solicitud."


def build_manager_graph(
    db: Any,
    llm: Optional[Any] = None,
    *,
    templates_root: Optional[Path] = None,
    db_path: Optional[str] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_base_url: Optional[str] = None,
) -> Any:
    """
    Construye el grafo manager: router -> invoke_worker.
    db: DuckClaw para agent_config y task_audit_log.
    """
    from langgraph.graph import END, StateGraph
    from duckclaw.graphs.on_the_fly_commands import (
        get_chat_state,
        get_team_templates,
        append_task_audit,
    )
    from duckclaw.graphs.activity import set_busy, set_idle
    from duckclaw.workers.factory import build_worker_graph as _build_worker_graph
    from duckclaw.workers.factory import list_workers

    if db_path is None:
        try:
            from duckclaw.gateway_db import get_gateway_db_path
            db_path = get_gateway_db_path()
        except Exception:
            db_path = ""

    # None -> use WORKERS_TEMPLATES_DIR (forge/templates) so workers are forge/templates/<id>/
    troot = templates_root

    def router_node(state: dict) -> dict:
        """Equipo del chat (get_team_templates) o todos los templates. El manager delega según el plan. Preserva incoming/history/chat_id."""
        chat_id = state.get("chat_id") or ""
        tenant_id = state.get("tenant_id") or "default"
        available = get_team_templates(db, chat_id) or list_workers(troot)
        assigned = available[0] if available else None
        out = {"assigned_worker_id": assigned, "available_templates": available}
        # Preservar estado para nodos siguientes (por si el grafo hace merge sustituyendo)
        if "incoming" in state:
            out["incoming"] = state["incoming"]
        if "input" in state:
            out["input"] = state["input"]
        if "history" in state:
            out["history"] = state["history"]
        if "chat_id" in state:
            out["chat_id"] = state["chat_id"]
        if "tenant_id" in state:
            out["tenant_id"] = state["tenant_id"]
        if "user_id" in state:
            out["user_id"] = state["user_id"]
        if "vault_db_path" in state:
            out["vault_db_path"] = state["vault_db_path"]
        return out

    def plan_node(state: ManagerAgentState) -> ManagerAgentState:
        """Formula un plan / tarea clara, genera plan_title/tasks y opcionalmente asigna finanz para intenciones DB/tablas."""
        _tid = (state.get("tenant_id") or "default").strip() or "default"
        _cid = (state.get("chat_id") or "").strip() or "unknown"
        set_log_context(tenant_id=_tid, worker_id="manager", chat_id=_cid)
        # Preservar incoming por si el estado no lo propaga (fallback: input, message)
        incoming = (state.get("incoming") or state.get("input") or state.get("message") or "").strip()
        available_plan = state.get("available_templates") or list_workers(troot)
        default_worker = available_plan[0] if available_plan else None
        assigned = (state.get("assigned_worker_id") or default_worker or "").strip() or default_worker
        if not incoming:
            _log.warning("manager plan: incoming vacío en state (keys=%s)", list(state.keys()))

        # Planner semántico: título + lista de tareas
        plan_title, tasks = _llm_plan(incoming)

        # Mantener lógica existente de ruteo / planned_task
        planned, override_worker = _plan_task(incoming, assigned)
        planned_final = planned or incoming

        # Derivar task_summary a partir del mensaje original / planned_task
        task_summary = _task_summary_for_activity(incoming, planned_final)

        out: ManagerAgentState = {
            "planned_task": planned_final,
            "incoming": incoming,
            "task_summary": task_summary,
            "plan_title": plan_title or None,
            "tasks": tasks or [],
        }  # type: ignore[assignment]

        if override_worker and override_worker in available_plan:
            out["assigned_worker_id"] = override_worker
        elif assigned not in available_plan and available_plan:
            out["assigned_worker_id"] = available_plan[0]
        else:
            out["assigned_worker_id"] = assigned

        out["available_templates"] = available_plan
        # Preservar estado para invoke_worker
        out["incoming"] = incoming or state.get("incoming") or state.get("input") or state.get("message") or ""
        out["input"] = out["incoming"]
        if "history" in state:
            out["history"] = state["history"]
        if "chat_id" in state:
            out["chat_id"] = state["chat_id"]
        if "tenant_id" in state:
            out["tenant_id"] = state["tenant_id"]
        if "user_id" in state:
            out["user_id"] = state["user_id"]
        if "vault_db_path" in state:
            out["vault_db_path"] = state["vault_db_path"]
        # Actualizar activity para /tasks usando solo el título del plan cuando esté disponible
        plan_for_task = (plan_title or "").strip()
        if plan_for_task:
            # Mostrar únicamente el título del plan en /tasks (sin corchetes)
            activity_task = plan_for_task
        else:
            activity_task = task_summary
        set_busy(state.get("chat_id") or "", task=activity_task, worker_id=out.get("assigned_worker_id", assigned))

        # Log del plan para PM2 / stdout, incluyendo plan_title + tasks (compacto)
        safe_title = (plan_title or "Sin título de plan").strip()
        if len(safe_title) > 80:
            safe_title = safe_title[:80] + "..."
        try:
            tasks_preview = ", ".join((tasks or [])[:3])
        except Exception:
            tasks_preview = ""
        if len(tasks_preview) > 160:
            tasks_preview = tasks_preview[:160] + "..."
        _assigned_for_log = (out.get("assigned_worker_id") or assigned or "").strip() or "?"
        log_plan(
            _obs,
            "[%s] -> tasks: [%s] | heur: [%s]",
            safe_title or "(vacío)",
            _assigned_for_log,
            tasks_preview or "(sin tareas)",
        )
        return out

    def invoke_worker_node(state: ManagerAgentState, config: RunnableConfig) -> ManagerAgentState:
        """Invoca el grafo del worker asignado; set_busy/set_idle y append_task_audit. Solo invoca si el worker existe en templates."""
        chat_id = state.get("chat_id") or ""
        tenant_id = state.get("tenant_id") or "default"
        user_id = state.get("user_id") or chat_id or "default"
        vault_db_path = (state.get("vault_db_path") or "").strip()
        incoming = (state.get("incoming") or state.get("input") or state.get("message") or "").strip()
        planned_task = (state.get("planned_task") or "").strip() or incoming
        plan_title = (state.get("plan_title") or "").strip() or None
        history = state.get("history") or []
        available = state.get("available_templates") or list_workers(troot)
        assigned = (state.get("assigned_worker_id") or "").strip() or None
        if assigned not in available:
            assigned = available[0] if available else None
        if assigned is None:
            set_idle(chat_id)
            _log.warning("manager: no hay plantillas de worker disponibles en %s", getattr(troot, "__str__", lambda: "")() or "forge/templates")
            # No incluir "messages": None — add_messages en ManagerAgentState exige valores no nulos.
            return {
                "reply": "No hay plantillas de worker configuradas. Añade al menos una en forge/templates (con manifest.yaml).",
                "_audit_done": True,
                "assigned_worker_id": None,
            }
        task_summary = (state.get("task_summary") or "").strip() or _task_summary_for_activity(incoming, planned_task)
        t0 = time.monotonic()
        reply = ""
        messages = None
        status = "SUCCESS"
        try:
            global _worker_graph_cache
            worker_cache_key = f"{tenant_id}::{assigned}::{vault_db_path or db_path or ''}"
            if worker_cache_key not in _worker_graph_cache:
                _worker_graph_cache[worker_cache_key] = _build_worker_graph(
                    assigned,
                    vault_db_path or db_path,
                    llm,
                    templates_root=troot,  # None => forge/templates
                    llm_provider=llm_provider or "",
                    llm_model=llm_model or "",
                    llm_base_url=llm_base_url or "",
                    instance_name=tenant_id,  # Aislar por tenant (Forge/WorkerFactory)
                )
            worker_graph = _worker_graph_cache[worker_cache_key]
            set_log_context(tenant_id=tenant_id, worker_id=assigned, chat_id=chat_id or "unknown")
            log_sys(_obs, "Delegación: manager -> %s", assigned)
            raw_sb = get_chat_state(db, chat_id, "sandbox_enabled")
            sb_on = (raw_sb or "").strip().lower() in ("true", "1", "on", "sí", "si")
            db_display = vault_db_path or db_path or "(unknown)"
            log_sys(
                _obs,
                "Sandbox: %s | DB: %s",
                "ON" if sb_on else "OFF",
                db_display,
            )
            # Pasar la tarea planificada al worker para que use herramientas y no responda genérico
            # Incluimos chat_id para que el worker pueda leer sandbox_enabled por sesión.
            worker_state = {
                "input": planned_task,
                "incoming": planned_task,
                "history": history,
                "chat_id": chat_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "vault_db_path": vault_db_path,
            }
            trace_cfg = get_tracing_config(
                tenant_id,
                assigned,
                str(chat_id or "unknown"),
                base=config,
            )
            result = worker_graph.invoke(worker_state, trace_cfg)
            reply = str(result.get("reply") or result.get("output") or "Sin respuesta.")
            messages = result.get("messages")
            # Log tool use para PM2 (tras manager plan)
            _tool_names = []
            for m in (messages or []):
                for tc in (getattr(m, "tool_calls", None) or []):
                    if isinstance(tc, dict) and tc.get("name"):
                        _tool_names.append(tc["name"])
                n = getattr(m, "name", None)
                if n:
                    _tool_names.append(n)
            _tools_list = list(dict.fromkeys(_tool_names))
            _log.info(
                "manager tool_use: delegó a worker=%s | tools usadas=%s",
                assigned,
                _tools_list if _tools_list else "ninguna",
            )
        except Exception as e:
            reply = str(e)[:2048]
            status = "FAILED"
        finally:
            set_idle(chat_id)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            append_task_audit(db, chat_id, assigned, incoming, status, elapsed_ms, plan_title=plan_title)

        # El manager ya registró en task_audit_log; el Gateway no debe duplicar.
        # assigned_worker_id para que el Gateway lo use en respuesta y trazas.
        # Solo añadir messages si el worker devolvió lista: None rompe add_messages en el estado.
        out: ManagerAgentState = {
            "reply": reply,
            "_audit_done": True,
            "assigned_worker_id": assigned,
            "plan_title": plan_title,
        }  # type: ignore[assignment]
        if messages is not None:
            out["messages"] = messages
        return out

    graph = StateGraph(ManagerAgentState)
    graph.add_node("router", router_node)
    graph.add_node("plan", plan_node)
    graph.add_node("invoke_worker", invoke_worker_node)
    graph.set_entry_point("router")
    graph.add_edge("router", "plan")
    graph.add_edge("plan", "invoke_worker")
    graph.add_edge("invoke_worker", END)
    return graph.compile()

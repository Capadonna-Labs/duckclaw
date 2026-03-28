"""
Manager graph: orquestador que asigna cada mensaje a un subagente (worker) y registra en /tasks y /history.

State: incoming, history, chat_id, reply, assigned_worker_id, planned_task, messages (opcional).
Flujo: router -> plan (formula tarea clara para el worker) -> invoke_worker (set_busy, invoca worker, set_idle, append_task_audit).
Spec: Plan manager orquestador de subagentes.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from duckclaw.forge.atoms.state import ManagerAgentState
from duckclaw.utils.langsmith_trace import get_tracing_config
from duckclaw.utils.logger import format_chat_log_identity, get_obs_logger, log_plan, log_sys, set_log_context

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
    # MVP Leila: saludos cortos → respuesta de tienda (evita tono “agente de investigación”).
    if (worker_id or "").strip() == "LeilaAssistant":
        plain = (incoming or "").strip()
        if len(plain) <= 24 and re.match(
            r"^(hola|hey|hi|hello|buen(as?|os)\s*(días|dias|tardes|noches)?|qué\s+tal|que\s+tal)[\s!?.¡¿]*$",
            plain.lower(),
        ):
            return (
                "TAREA: El cliente saluda. Preséntate en 2–3 frases como Leila Store (tienda de ropa): "
                "tono cálido y directo. Menciona /catalogo para ver productos y /pedido <id> <talla> para pedir. "
                "No digas que eres un agente de investigación ni listes herramientas genéricas.",
                None,
            )
    # Intención DB/tablas/nombre → si el rol es personalizable, usar finanz (especialista) si está disponible
    is_db_intent = (
        re.search(r"\b(nombre\s+de\s+la\s+db|db|tablas?|tables?|esquema|schema|estructura|disponibles)\b", t)
        or "tablas" in t
        or ("nombre" in t and ("db" in t or "base" in t or "datos" in t))
    )
    if is_db_intent and (worker_id or "").strip().lower() == "personalizable":
        override = "finanz"  # invoke_worker lo usará si finanz está en list_workers

    # Última partida / partida más reciente
    is_latest_game_intent = bool(
        re.search(
            r"\b(ultima|última|mas\s+reciente|más\s+reciente)\s+partida\b",
            t,
        )
    ) or ("partida" in t and ("ultima" in t or "última" in t or "reciente" in t))
    if is_latest_game_intent:
        task = (
            "TAREA: El usuario quiere conocer la última partida de The Mind. "
            "Ejecuta read_sql con una consulta directa sobre the_mind_games para traer solo 1 registro "
            "(prioriza ORDER BY game_id DESC LIMIT 1, o por created_at si esa columna existe). "
            "Si la consulta falla por columna inexistente, corrige automáticamente y reintenta sin preguntar. "
            "Responde con game_id, status, current_level, lives y shurikens."
        )
        return task, override

    # Nombre de la db / base de datos
    if re.search(r"\b(nombre\s+de\s+la\s+db|nombre\s+db|cual\s+es\s+el\s+nombre|nombre\s+de\s+la\s+base)\b", t) or (
        "nombre" in t and ("db" in t or "base" in t or "datos" in t)
    ):
        task = (
            "TAREA: El usuario quiere saber qué base de datos se está usando. "
            "Ejecuta get_db_path y responde de forma proactiva: indica la db usada en texto plano (sin comillas ni negrita). En el cierre invita a /team, /tasks, /help y a crear objetivos con /goals (por defecto están vacíos). Usa 1-2 emojis si encaja."
        )
        return task, override
    # Contenido de una tabla concreta
    is_table_content_intent = bool(
        re.search(
            r"\b(que\s+hay\s+en\s+la\s+tabla|qué\s+hay\s+en\s+la\s+tabla|contenido\s+de\s+la\s+tabla|"
            r"muestr(a|ame)\s+la\s+tabla|ver\s+datos\s+de\s+la\s+tabla|registros?\s+de\s+la\s+tabla|"
            r"filas?\s+de\s+la\s+tabla|select\s+\*\s+from)\b",
            t,
        )
    )
    if is_table_content_intent:
        table_name: Optional[str] = None
        m_from = re.search(r"\bfrom\s+([a-zA-Z_][\w.]*)\b", t)
        if m_from:
            table_name = m_from.group(1)
        if not table_name:
            m_tabla = re.search(r"\btabla\s+([a-zA-Z_][\w.]*)\b", t)
            if m_tabla:
                table_name = m_tabla.group(1)
        if not table_name:
            m_registros = re.search(r"\bregistros?\s+de\s+([a-zA-Z_][\w.]*)\b", t)
            if m_registros:
                table_name = m_registros.group(1)

        if table_name:
            task = (
                "TAREA: El usuario quiere ver el contenido de una tabla específica. "
                f"Ejecuta read_sql con SELECT * FROM {table_name} LIMIT 20. "
                "Si falla por nombre/esquema, corrige al esquema válido sin pedir aclaración innecesaria. "
                "Explica brevemente las columnas visibles y ofrece profundizar con filtros."
            )
            return task, override

        task = (
            "TAREA: El usuario quiere ver el contenido de una tabla específica. "
            "Ejecuta read_sql con SELECT * FROM <tabla> LIMIT 20 (o una consulta equivalente segura), "
            "explica brevemente las columnas visibles y ofrece profundizar con filtros."
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
    if "partida" in lower and ("ultima" in lower or "última" in lower or "reciente" in lower):
        title = "Consulta de Última Partida"
    elif (
        re.search(
            r"\b(que\s+hay\s+en\s+la\s+tabla|qué\s+hay\s+en\s+la\s+tabla|contenido\s+de\s+la\s+tabla|"
            r"muestr(a|ame)\s+la\s+tabla|ver\s+datos\s+de\s+la\s+tabla|registros?\s+de\s+la\s+tabla|"
            r"filas?\s+de\s+la\s+tabla|select\s+\*\s+from)\b",
            lower,
        )
        is not None
    ):
        title = "Consulta de Contenido de Tabla"
    elif "saldo" in lower or "dinero" in lower or "cuenta" in lower:
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


def _truncate_plan_title_words(title: str, max_words: int = 5) -> str:
    """Recorta el título del plan a como mucho `max_words` palabras."""
    words = (title or "").strip().split()
    if not words:
        return ""
    return " ".join(words[:max_words])


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """Parsea JSON del texto completo o del primer objeto {...} embebido."""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _coerce_planner_payload(data: Any) -> tuple[str, list[str]]:
    """Valida el dict del LLM; lanza ValueError si no cumple el contrato."""
    if not isinstance(data, dict):
        raise ValueError("planner payload is not an object")
    title = data.get("plan_title")
    if title is None or not str(title).strip():
        raise ValueError("missing plan_title")
    tasks_raw = data.get("tasks")
    if tasks_raw is None:
        tasks_list: list[str] = []
    elif isinstance(tasks_raw, list):
        tasks_list = [str(x).strip() for x in tasks_raw if str(x).strip()]
    else:
        raise ValueError("tasks must be a list")
    return str(title).strip(), tasks_list


def _llm_plan_from_model(llm: Any, incoming: str, planner_system_prompt: str) -> Optional[tuple[str, list[str]]]:
    """
    Invoca el LLM del Manager para obtener {"plan_title", "tasks"}.
    Devuelve None si falla el invoke, el parse o el contrato (el caller usa heurística).
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    append = (os.environ.get("DUCKCLAW_MANAGER_PLANNER_SYSTEM_APPEND") or "").strip()
    system_chunks = [planner_system_prompt.strip(), append]
    system_chunks.append(
        'Responde únicamente con JSON válido (sin markdown): '
        '{"plan_title": "string", "tasks": ["string", ...]}'
    )
    system = "\n\n".join(c for c in system_chunks if c)
    human = f"Mensaje del usuario:\n{(incoming or '').strip()}"
    try:
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
    except Exception as exc:
        _log.debug("manager planner LLM invoke failed: %s", exc)
        return None
    content: Any = getattr(resp, "content", None)
    if content is None:
        content = str(resp)
    if isinstance(content, list):
        content = "".join(
            (p.get("text", "") if isinstance(p, dict) else str(p)) for p in content
        )
    raw_text = str(content).strip()
    data = _extract_json_object(raw_text)
    if data is None:
        _log.debug("manager planner: no JSON object in model output")
        return None
    try:
        title, tasks = _coerce_planner_payload(data)
    except ValueError as exc:
        _log.debug("manager planner: invalid payload: %s", exc)
        return None
    title = _truncate_plan_title_words(title, 5)
    if not title:
        return None
    if not tasks:
        clip = (incoming or "").strip()[:200]
        tasks = [f"Resolver la solicitud del usuario: {clip}" if clip else "Resolver solicitud del usuario"]
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
    planner_system_prompt: str = "",
) -> Any:
    """
    Construye el grafo manager: router -> invoke_worker.
    db: DuckClaw para agent_config y task_audit_log.
    """
    from langgraph.graph import END, StateGraph
    from duckclaw.graphs.on_the_fly_commands import (
        get_chat_state,
        get_effective_team_templates,
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
        """Equipo efectivo: chat > tenant > env > todos. El manager delega según el plan. Preserva incoming/history/chat_id."""
        chat_id = state.get("chat_id") or ""
        tenant_id = state.get("tenant_id") or "default"
        available = list(get_effective_team_templates(db, chat_id, tenant_id, troot))
        preferred = (os.environ.get("DUCKCLAW_DEFAULT_WORKER_ID") or "").strip()
        assigned = available[0] if available else None
        if preferred and available:
            for wid in available:
                if (wid or "").strip().lower() == preferred.lower():
                    assigned = (wid or "").strip()
                    break
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
        if "shared_db_path" in state:
            out["shared_db_path"] = state["shared_db_path"]
        if "username" in state:
            out["username"] = state["username"]
        return out

    def plan_node(state: ManagerAgentState) -> ManagerAgentState:
        """Formula un plan / tarea clara, genera plan_title/tasks y opcionalmente asigna finanz para intenciones DB/tablas."""
        _tid = (state.get("tenant_id") or "default").strip() or "default"
        _cid = (state.get("chat_id") or "").strip() or "unknown"
        set_log_context(
            tenant_id=_tid,
            worker_id="manager",
            chat_id=format_chat_log_identity(_cid, state.get("username")),
        )
        # Preservar incoming por si el estado no lo propaga (fallback: input, message)
        incoming = (state.get("incoming") or state.get("input") or state.get("message") or "").strip()
        available_plan = state.get("available_templates") or list_workers(troot)
        default_worker = available_plan[0] if available_plan else None
        assigned = (state.get("assigned_worker_id") or default_worker or "").strip() or default_worker
        if not incoming:
            _log.warning("manager plan: incoming vacío en state (keys=%s)", list(state.keys()))

        _psp = (planner_system_prompt or "").strip()
        if llm is not None and _psp:
            _parsed = _llm_plan_from_model(llm, incoming, _psp)
            if _parsed:
                plan_title, tasks = _parsed
            else:
                plan_title, tasks = _llm_plan(incoming)
        else:
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
        if "shared_db_path" in state:
            out["shared_db_path"] = state["shared_db_path"]
        if "username" in state:
            out["username"] = state["username"]
        # Actualizar activity para /tasks usando solo el título del plan cuando esté disponible
        plan_for_task = (plan_title or "").strip()
        if plan_for_task:
            # Mostrar únicamente el título del plan en /tasks (sin corchetes)
            activity_task = plan_for_task
        else:
            activity_task = task_summary
        set_busy(state.get("chat_id") or "", task=activity_task, worker_id=out.get("assigned_worker_id", assigned))

        # Log del plan para PM2 / stdout: título + lista de tasks (worker en línea aparte)
        safe_title = (plan_title or "Sin título de plan").strip()
        if len(safe_title) > 80:
            safe_title = safe_title[:80] + "..."
        try:
            _tlist = list(tasks or [])[:8]
            tasks_preview = ", ".join(_tlist)
            if len(tasks or []) > 8:
                tasks_preview += ", …"
        except Exception:
            tasks_preview = ""
        if len(tasks_preview) > 200:
            tasks_preview = tasks_preview[:200] + "…"
        log_plan(
            _obs,
            '"%s" | tasks: [%s]',
            safe_title or "(vacío)",
            tasks_preview if tasks_preview else "(sin tareas)",
        )
        _assigned_for_log = (out.get("assigned_worker_id") or assigned or "").strip() or "?"
        log_sys(_obs, "Worker elegido para el plan: %s", _assigned_for_log)
        return out

    def invoke_worker_node(state: ManagerAgentState, config: RunnableConfig) -> ManagerAgentState:
        """Invoca el grafo del worker asignado; set_busy/set_idle y append_task_audit. Solo invoca si el worker existe en templates."""
        chat_id = state.get("chat_id") or ""
        tenant_id = state.get("tenant_id") or "default"
        user_id = state.get("user_id") or chat_id or "default"
        vault_db_path = (state.get("vault_db_path") or "").strip()
        shared_db_path = (state.get("shared_db_path") or "").strip()
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
            worker_cache_key = f"{tenant_id}::{assigned}::{vault_db_path or db_path or ''}::{shared_db_path}"
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
                    shared_db_path=shared_db_path or None,
                )
            worker_graph = _worker_graph_cache[worker_cache_key]
            set_log_context(
                tenant_id=tenant_id,
                worker_id=assigned,
                chat_id=format_chat_log_identity(chat_id or "unknown", state.get("username")),
            )
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
                "username": (state.get("username") or "").strip(),
                "vault_db_path": vault_db_path,
                "shared_db_path": shared_db_path,
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

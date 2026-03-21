"""General agent graph: SQL + schema + memory + sandbox tools, supports incoming + history."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

_log = logging.getLogger(__name__)

from duckclaw.graphs.tools import read_sql, admin_sql, inspect_schema, manage_memory, get_db_path


_DB_INTENT_RE = re.compile(
    r"\b(sql|tabla|tablas|schema|esquema|columna|columnas|base de datos|db|"
    r"ventas|vendedor|clientes|productos|pedidos|orders|seller|count|cu[aá]nt[ao]s?)\b",
    re.IGNORECASE,
)

_SANDBOX_INTENT_RE = re.compile(
    r"\b(ejecuta|corre|run|script|código|codigo|python|bash|programa|simula|modela|"
    r"predic|forecast|entren|train|modelo|model|análisis\s+libre|sandbox)\b",
    re.IGNORECASE,
)


def _needs_db_tool(incoming: str) -> bool:
    text = (incoming or "").strip()
    if not text:
        return False
    return bool(_DB_INTENT_RE.search(text)) or "?" in text


def _needs_sandbox_tool(incoming: str) -> bool:
    return bool(_SANDBOX_INTENT_RE.search(incoming or ""))


_DEFAULT_SYSTEM_PROMPT = (
    "Eres un asistente útil con acceso a una base de datos DuckDB y a un sandbox de ejecución Python/Bash. "
    "Cuando uses una herramienta, interpreta el resultado y responde en lenguaje natural claro y conciso. "
    "Nunca copies el resultado crudo de una herramienta. "
    "Si hay una lista de tablas, menciónalas de forma legible. "
    "Si hay datos de una consulta, preséntelos de forma organizada. "
    "Usa run_sandbox para ejecutar código Python o Bash arbitrario cuando el usuario lo pida. "
    "Estilo de respuesta: sé conciso y directo; usa como máximo 1 o 2 emojis por mensaje si aportan claridad; evita listas largas sin resumir, encabezados markdown (##) y relleno; responde con lo esencial."
)

_DEFAULT_TOOLS = ["read_sql", "admin_sql", "inspect_schema", "manage_memory", "get_db_path", "run_sandbox"]


def _format_incoming_with_identity(state: dict) -> str:
    """
    Formatea el mensaje entrante inyectando identidad multi-usuario cuando haya metadatos.

    - Si el estado incluye username/chat_type y es group/supergroup, devuelve "[username]: mensaje".
    - En caso contrario, devuelve el incoming/message sin prefijo.
    """
    incoming = state.get("incoming")
    if incoming is None:
        incoming = state.get("message") or ""
    incoming = str(incoming or "")
    chat_type = str(state.get("chat_type") or "").strip().lower()
    username = str(state.get("username") or "").strip()
    if chat_type in ("group", "supergroup") and username:
        return f"[{username}]: {incoming}"
    return incoming


def build_general_graph(
    db: Any,
    llm: Any,
    *,
    system_prompt: str = "",
    tools_spec: list[str] | None = None,
) -> Any:
    """
    Build LangGraph for general assistant: state has 'incoming', optional 'history'; result has 'reply'.
    Usa read_sql/admin_sql, inspect_schema, manage_memory, run_sandbox (Strix).
    system_prompt y tools_spec vienen del YAML o del caller (AgentAssembler).
    """
    from langgraph.graph import END, StateGraph
    from langchain_core.tools import StructuredTool
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

    prompt = (system_prompt or _DEFAULT_SYSTEM_PROMPT).strip()
    if prompt and "estilo" not in prompt.lower() and "conciso" not in prompt.lower():
        prompt += "\n\nEstilo: respuestas concisas, 1-2 emojis como máximo, sin relleno ni listas largas innecesarias."
    tool_names = tools_spec if tools_spec is not None else _DEFAULT_TOOLS
    tool_names_set = frozenset(str(t).strip() for t in tool_names if t is not None and str(t).strip())

    tools: list[Any] = []
    if "read_sql" in tool_names_set:
        tools.append(
            StructuredTool.from_function(
                lambda q: read_sql(db, q),
                name="read_sql",
                description="Solo lectura SQL (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN/PRAGMA).",
            )
        )
    if "admin_sql" in tool_names_set:
        tools.append(
            StructuredTool.from_function(
                lambda q: admin_sql(db, q),
                name="admin_sql",
                description="Admin SQL: lectura + escrituras (INSERT/UPDATE/DELETE/CREATE/ALTER/DROP si el contexto lo permite).",
            )
        )
    # Nota: solo existen read_sql/admin_sql para la capa SQL.
    if "inspect_schema" in tool_names_set:
        tools.append(
            StructuredTool.from_function(
                lambda: inspect_schema(db),
                name="inspect_schema",
                description="Lista tablas y columnas de la base de datos actual.",
            )
        )
    if "get_db_path" in tool_names_set:
        tools.append(
            StructuredTool.from_function(
                lambda: get_db_path(db),
                name="get_db_path",
                description="Devuelve la ruta o nombre del archivo .duckdb al que tienes acceso. Úsala cuando pregunten qué base de datos usas o el nombre del archivo.",
            )
        )
    if "manage_memory" in tool_names_set:
        tools.append(
            StructuredTool.from_function(
                lambda action, key, value="": manage_memory(db, action, key, value),
                name="manage_memory",
                description="Preferencias del usuario: action=get|set|delete, key, value (solo para set).",
            )
        )

    # Memoria triple (plantilla industry v3.0): tool explícita o si DUCKCLAW_INDUSTRY_TEMPLATE está definido
    _industry_tpl = (os.environ.get("DUCKCLAW_INDUSTRY_TEMPLATE") or "").strip()
    if "unified_memory" in tool_names_set or _industry_tpl:
        try:
            from duckclaw.forge.skills.unified_memory_orchestrator import make_unified_memory_tool

            tools.append(make_unified_memory_tool(db))
        except Exception:
            pass

    # Sandbox (Strix) — solo si está en tools_spec y Docker está disponible
    if "run_sandbox" in tool_names_set:
        try:
            from duckclaw.graphs.sandbox import sandbox_tool_factory, _docker_available
            if _docker_available():
                tools.append(sandbox_tool_factory(db, llm))
        except Exception:
            pass

    # Research (Tavily + Browser-Use) — opcional vía tools_spec
    if "tavily_search" in tool_names_set or "browser_navigate" in tool_names_set:
        try:
            from duckclaw.forge.skills.research_bridge import register_research_skill
            research_cfg = {
                "tavily_enabled": "tavily_search" in tool_names_set,
                "browser_enabled": "browser_navigate" in tool_names_set,
            }
            register_research_skill(tools, research_cfg, llm=llm)
        except Exception:
            pass

    # Tailscale Mesh — opcional vía tools_spec
    if "tailscale_status" in tool_names_set:
        try:
            from duckclaw.forge.skills.tailscale_bridge import register_tailscale_skill
            register_tailscale_skill(tools, {"tailscale_enabled": True})
        except Exception:
            pass

    # SFT pipeline — opcional vía tools_spec
    if "collect_sft_dataset" in tool_names_set:
        try:
            from duckclaw.forge.skills.sft_bridge import register_sft_skill
            register_sft_skill(tools, {"sft_enabled": True})
        except Exception:
            pass

    # ContextHubBridge — Ground Truth de APIs externas opcional vía tools_spec
    if "context_hub_bridge" in tool_names_set:
        try:
            from duckclaw.forge.skills.context_hub_bridge import register_context_hub_skill

            register_context_hub_skill(tools, {"enabled": True})
        except Exception:
            pass

    # SendPrivateMessage / send_dm — opcional vía tools_spec
    if "send_dm" in tool_names_set:
        try:
            from duckclaw.forge.skills.send_dm_bridge import register_send_dm_skill

            register_send_dm_skill(tools, {"enabled": True})
        except Exception:
            pass

    # The Mind broadcasting / reparto de cartas — opcional vía tools_spec
    if "broadcast_message" in tool_names_set or "deal_cards" in tool_names_set:
        try:
            from duckclaw.forge.skills.broadcast import broadcast_message, deal_cards

            if "broadcast_message" in tool_names_set:
                tools.append(broadcast_message)
            if "deal_cards" in tool_names_set:
                tools.append(deal_cards)
        except Exception:
            pass

    # Mensajería proactiva outbound (n8n) — opcional vía tools_spec
    if "send_proactive_message" in tool_names_set:
        try:
            from duckclaw.forge.skills.outbound_messaging import send_proactive_message

            tools.append(send_proactive_message)
        except Exception:
            pass

    # TimeContextSkill — contexto temporal (America/Bogota) opcional vía tools_spec
    if "get_current_time" in tool_names_set or "time_context" in tool_names_set:
        try:
            from duckclaw.forge.skills.time_context import get_current_time

            tools.append(get_current_time)
        except Exception:
            pass

    llm_with_tools = llm.bind_tools(tools)
    llm_with_required_tool = llm.bind_tools(tools, tool_choice="required")
    tools_by_name = {t.name: t for t in tools}

    def prepare_node(state: dict) -> dict:
        base_prompt = prompt
        graph_ctx = (state.get("graph_context") or "").strip()
        if graph_ctx:
            base_prompt = base_prompt + "\n\n" + graph_ctx
        messages = [SystemMessage(content=base_prompt)]
        for h in (state.get("history") or []):
            role = (h.get("role") or "").lower()
            content = h.get("content") or ""
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        incoming = _format_incoming_with_identity(state)
        messages.append(HumanMessage(content=incoming))
        return {"messages": messages}

    def agent_node(state: dict) -> dict:
        incoming = state.get("incoming") or ""
        has_sandbox = "run_sandbox" in tools_by_name
        if _needs_sandbox_tool(incoming) and has_sandbox:
            llm_runner = llm.bind_tools(tools, tool_choice={"type": "function", "function": {"name": "run_sandbox"}})
        elif _needs_db_tool(incoming):
            llm_runner = llm_with_required_tool
        else:
            llm_runner = llm_with_tools
        try:
            resp = llm_runner.invoke(state["messages"])
        except Exception:
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
            _log.info("tool_use: %s %s", name, json.dumps(args, default=str)[:200])
            tool = tools_by_name.get(name)
            if tool:
                try:
                    import time as _time

                    t0 = _time.monotonic()
                    result = tool.invoke(args)
                    duration_ms = int((_time.monotonic() - t0) * 1000)
                    # Auditoría específica para TimeContextSkill
                    if name == "get_current_time":
                        try:
                            from duckclaw.graphs.on_the_fly_commands import append_task_audit
                            from duckclaw.graphs.graph_server import get_db

                            db = get_db()
                            tenant_id = state.get("chat_id") or ""
                            worker_id = state.get("assigned_worker_id") or ""
                            append_task_audit(
                                db,
                                tenant_id,
                                worker_id,
                                "Consulta de contexto temporal",
                                "SUCCESS",
                                duration_ms,
                            )
                        except Exception:
                            pass
                    content = str(result) if result is not None else "OK"
                except Exception as e:
                    content = f"Error: {e}"
            else:
                content = f"Herramienta desconocida: {name}"
            new_msgs.append(ToolMessage(content=content, tool_call_id=tid, name=name))
        return {"messages": new_msgs}

    def set_reply(state: dict) -> dict:
        import json

        from duckclaw.integrations.llm_providers import _strip_eot

        msgs = state["messages"]
        last = msgs[-1]
        reply = getattr(last, "content", None) or str(last)
        reply = _strip_eot(reply or "").strip()
        # Model returned tool call as text (e.g. Slayer-8B without native tool_calls)
        if reply.startswith("{") and '"name"' in reply and ("parameters" in reply or '"args"' in reply):
            try:
                from duckclaw.utils import format_tool_reply

                data = json.loads(reply)
                name = data.get("name") or data.get("tool")
                params = data.get("parameters") or data.get("args") or {}
                if name and name in tools_by_name:
                    result = tools_by_name[name].invoke(params)
                    text = str(result) if result else "Listo."
                    return {"reply": format_tool_reply(text), "messages": msgs}
            except (json.JSONDecodeError, TypeError, KeyError, Exception):
                pass
        return {"reply": reply or "", "messages": msgs}

    def should_continue(state: dict) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else "end"

    graph = StateGraph(dict)
    graph.add_node("prepare", prepare_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("set_reply", set_reply)
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": "set_reply"})
    graph.add_edge("tools", "agent")
    graph.add_edge("set_reply", END)
    return graph.compile()

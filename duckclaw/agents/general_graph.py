"""General agent graph: SQL + schema + memory tools, supports incoming + history."""

from __future__ import annotations

import re
from typing import Any

from duckclaw.agents.tools import run_sql, inspect_schema, manage_memory


_DB_INTENT_RE = re.compile(
    r"\b(sql|tabla|tablas|schema|esquema|columna|columnas|base de datos|db|"
    r"ventas|vendedor|clientes|productos|pedidos|orders|seller|count|cu[aá]nt[ao]s?)\b",
    re.IGNORECASE,
)


def _needs_db_tool(incoming: str) -> bool:
    text = (incoming or "").strip()
    if not text:
        return False
    return bool(_DB_INTENT_RE.search(text)) or "?" in text


def build_general_graph(
    db: Any,
    llm: Any,
    *,
    system_prompt: str = "",
) -> Any:
    """
    Build LangGraph for general assistant: state has 'incoming', optional 'history'; result has 'reply'.
    Uses run_sql, inspect_schema, manage_memory.
    """
    from langgraph.graph import END, StateGraph
    from langchain_core.tools import StructuredTool
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

    prompt = system_prompt or (
        "Eres un asistente útil con acceso a una base de datos DuckDB. "
        "Cuando uses una herramienta, interpreta el resultado y responde en lenguaje natural claro y conciso. "
        "Nunca copies el resultado crudo de una herramienta. "
        "Si hay una lista de tablas, menciónalas de forma legible. "
        "Si hay datos de una consulta, preséntelos de forma organizada."
    )
    tools = [
        StructuredTool.from_function(
            lambda q: run_sql(db, q),
            name="run_sql",
            description="Ejecuta una consulta SQL y retorna JSON. Usa para leer o escribir datos.",
        ),
        StructuredTool.from_function(
            lambda: inspect_schema(db),
            name="inspect_schema",
            description="Lista tablas y columnas de la base de datos actual.",
        ),
        StructuredTool.from_function(
            lambda action, key, value="": manage_memory(db, action, key, value),
            name="manage_memory",
            description="Preferencias del usuario: action=get|set|delete, key, value (solo para set).",
        ),
    ]
    llm_with_tools = llm.bind_tools(tools)
    llm_with_required_tool = llm.bind_tools(tools, tool_choice="required")
    tools_by_name = {t.name: t for t in tools}

    def prepare_node(state: dict) -> dict:
        messages = [SystemMessage(content=prompt)]
        for h in (state.get("history") or []):
            role = (h.get("role") or "").lower()
            content = h.get("content") or ""
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        messages.append(HumanMessage(content=state.get("incoming") or ""))
        return {"messages": messages}

    def agent_node(state: dict) -> dict:
        incoming = state.get("incoming") or ""
        llm_runner = llm_with_required_tool if _needs_db_tool(incoming) else llm_with_tools
        resp = llm_runner.invoke(state["messages"])
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
                    return {"reply": format_tool_reply(text)}
            except (json.JSONDecodeError, TypeError, KeyError, Exception):
                pass
        return {"reply": reply or ""}

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

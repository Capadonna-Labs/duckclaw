"""General agent graph: SQL + schema + memory + sandbox tools, supports incoming + history."""

from __future__ import annotations

import re
from typing import Any

from duckclaw.agents.tools import run_sql, inspect_schema, manage_memory


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
    "Usa run_sandbox para ejecutar código Python o Bash arbitrario cuando el usuario lo pida."
)

_DEFAULT_TOOLS = ["run_sql", "inspect_schema", "manage_memory", "run_sandbox"]


def build_general_graph(
    db: Any,
    llm: Any,
    *,
    system_prompt: str = "",
    tools_spec: list[str] | None = None,
) -> Any:
    """
    Build LangGraph for general assistant: state has 'incoming', optional 'history'; result has 'reply'.
    Uses run_sql, inspect_schema, manage_memory, run_sandbox (Strix).
    system_prompt y tools_spec vienen del YAML o del caller (AgentAssembler).
    """
    from langgraph.graph import END, StateGraph
    from langchain_core.tools import StructuredTool
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

    prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
    tool_names = tools_spec if tools_spec is not None else _DEFAULT_TOOLS
    tool_names_set = frozenset(str(t).strip() for t in tool_names if t is not None and str(t).strip())

    tools: list[Any] = []
    if "run_sql" in tool_names_set:
        tools.append(
            StructuredTool.from_function(
                lambda q: run_sql(db, q),
                name="run_sql",
                description="Ejecuta una consulta SQL y retorna JSON. Usa para leer o escribir datos.",
            )
        )
    if "inspect_schema" in tool_names_set:
        tools.append(
            StructuredTool.from_function(
                lambda: inspect_schema(db),
                name="inspect_schema",
                description="Lista tablas y columnas de la base de datos actual.",
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

    # Sandbox (Strix) — solo si está en tools_spec y Docker está disponible
    if "run_sandbox" in tool_names_set:
        try:
            from duckclaw.agents.sandbox import sandbox_tool_factory, _docker_available
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
        messages.append(HumanMessage(content=state.get("incoming") or ""))
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

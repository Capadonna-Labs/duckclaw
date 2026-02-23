"""Grafo LangGraph para el Contador Soberano de Retail (Capa de Negocio IoTCoreLabs)."""

from __future__ import annotations

from typing import Any, Optional

SYSTEM_PROMPT = """Eres el Contador Soberano de Retail de IoTCoreLabs. Actúas con precisión y cuidado sobre finanzas e inventario.

Reglas de uso de herramientas:
- Si el usuario reporta una venta (vendí X, se vendió Y, registra venta de Z), usa siempre la herramienta 'register_sale' con item_name, size, price y method.
- Si el usuario pregunta qué hay, qué queda, inventario, stock o listar productos, usa 'check_inventory' (opcionalmente con name_filter o size_filter).
- Si el usuario reporta un gasto (arriendo, servicios, gasto personal), usa 'record_expense' con amount, expense_type ('BUSINESS' o 'PERSONAL'), payment_method y notes.

Sé extremadamente cuidadoso con los números: verifica cantidades y precios antes de registrar. Responde de forma breve y clara en español."""


def build_retail_graph(
    store_db: Any,
    llm: Any,
    console: Optional[Any] = None,
) -> Any:
    """Construye el grafo LangGraph para el agente retail: state 'incoming', result 'reply'."""
    from langgraph.graph import END, StateGraph

    from .tools import build_store_tools

    tools = build_store_tools(store_db, console=console)
    llm_with_tools = llm.bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    def prepare_node(state: dict) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage

        incoming = (state.get("incoming") or "").strip()
        return {
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=incoming),
            ]
        }

    def agent_node(state: dict) -> dict:
        messages = state.get("messages") or []
        response = llm_with_tools.invoke(messages)
        return {"messages": messages + [response]}

    def tools_node(state: dict) -> dict:
        from langchain_core.messages import ToolMessage

        messages = state.get("messages") or []
        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        tool_messages = []
        for tc in tool_calls:
            name = tc.get("name") or ""
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
            tool_messages.append(ToolMessage(content=content, tool_call_id=tid))
        return {"messages": messages + tool_messages}

    def set_reply_node(state: dict) -> dict:
        import json
        messages = state.get("messages") or []
        last = messages[-1]
        reply = getattr(last, "content", None) or str(last)
        for token in ("<|eot_id|>", "<|end|>", "<|end_of_text|>"):
            if reply.endswith(token):
                reply = reply[: -len(token)].strip()
        reply = reply.strip()
        # Si el modelo devolvió un tool call como texto (ej. Slayer-8B), ejecutarlo y usar el resultado
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
        return {"reply": reply}

    def should_continue(state: dict) -> str:
        messages = state.get("messages") or []
        if not messages:
            return "end"
        last = messages[-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return "end"

    graph = StateGraph(dict)
    graph.add_node("prepare", prepare_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("set_reply", set_reply_node)
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": "set_reply"})
    graph.add_edge("tools", "agent")
    graph.add_edge("set_reply", END)
    return graph.compile()

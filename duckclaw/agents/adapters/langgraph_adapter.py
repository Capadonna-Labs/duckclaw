"""Adapter LangGraph: grafo ReAct simple con herramientas SQL."""

from __future__ import annotations

from typing import Any, List, Optional

from .base import BaseAgent


class LangGraphAdapter(BaseAgent):
    """Grafo ReAct con run_sql, inspect_schema y manage_memory sobre DuckClaw.
    provider/model/base_url se pueden configurar desde la TUI (wizard) o /setup."""

    def __init__(
        self,
        db: Any,
        system_prompt: str = "",
        provider: str = "",
        model: str = "",
        base_url: str = "",
    ) -> None:
        self.db = db
        self._system_prompt = system_prompt or "Eres un asistente útil con acceso a una base de datos. Usa las herramientas cuando sea necesario."
        self._provider = (provider or "").strip().lower()
        self._model = (model or "").strip()
        self._base_url = (base_url or "").strip()

    def with_system_prompt(self, system_prompt: str) -> "LangGraphAdapter":
        self._system_prompt = system_prompt or self._system_prompt
        return self

    def invoke(self, message: str, history: Optional[List[dict]] = None) -> str:
        try:
            from langgraph.graph import END, StateGraph
            from langchain_core.tools import StructuredTool
            from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
        except ImportError as e:
            return f"Error: instala el extra langgraph. {e}"

        from duckclaw.agents.tools import run_sql, inspect_schema, manage_memory

        db = self.db
        system_prompt = self._system_prompt

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
        llm = self._get_llm()
        if llm is None:
            return "Error: proveedor 'none_llm' no soportado en este adapter. Usa llm_provider=openai, anthropic, mlx o iotcorelabs."
        llm_with_tools = llm.bind_tools(tools)
        tools_by_name = {t.name: t for t in tools}

        def prepare_node(state: dict) -> dict:
            messages = [SystemMessage(content=system_prompt)]
            for h in (state.get("history") or []):
                role = (h.get("role") or "").lower()
                content = h.get("content") or ""
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
            messages.append(HumanMessage(content=state.get("message") or ""))
            return {"messages": messages}

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
            msgs = state["messages"]
            last = msgs[-1]
            reply = getattr(last, "content", None) or str(last)
            return {"reply": (reply or "").strip()}

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
        app = graph.compile()

        out = app.invoke({"message": message, "history": history or []})
        return out.get("reply") or ""

    def _get_llm(self) -> Any:
        # Si hay provider configurado (TUI o /setup), usar build_llm del proyecto
        if self._provider and self._provider != "none_llm":
            try:
                from duckclaw.integrations.llm_providers import build_llm
                return build_llm(self._provider, self._model, self._base_url)
            except Exception as e:
                raise RuntimeError(str(e)) from e
        # Fallback: env (OpenAI o Anthropic)
        import os
        if os.environ.get("OPENAI_API_KEY"):
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
        if os.environ.get("ANTHROPIC_API_KEY"):
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"), temperature=0)
        raise RuntimeError(
            "Configura el model provider en la TUI (./scripts/install_duckclaw.sh) o con /setup llm_provider=openai|anthropic|mlx|iotcorelabs. "
            "O añade OPENAI_API_KEY / ANTHROPIC_API_KEY en .env."
        )
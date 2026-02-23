"""Adapter OpenAI: SDK oficial con Tool Calling."""

from __future__ import annotations

from typing import Any, List, Optional

from .base import BaseAgent


def _openai_tools_spec() -> List[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "run_sql",
                "description": "Ejecuta una consulta SQL y retorna JSON.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Sentencia SQL"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "inspect_schema",
                "description": "Lista tablas y columnas de la base de datos.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "manage_memory",
                "description": "Preferencias: action=get|set|delete, key, value (opcional para set).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get", "set", "delete"]},
                        "key": {"type": "string"},
                        "value": {"type": "string", "description": "Solo para action=set"},
                    },
                    "required": ["action", "key"],
                },
            },
        },
    ]


class OpenAIAdapter(BaseAgent):
    """Usa el SDK oficial openai con Tool Calling sobre DuckClaw."""

    def __init__(self, db: Any, system_prompt: str = "") -> None:
        self.db = db
        self._system_prompt = system_prompt or "Eres un asistente útil con acceso a una base de datos."

    def with_system_prompt(self, system_prompt: str) -> "OpenAIAdapter":
        self._system_prompt = system_prompt or self._system_prompt
        return self

    def invoke(self, message: str, history: Optional[List[dict]] = None) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            return "Error: instala el extra openai (pip install duckclaw[openai])."

        from duckclaw.agents.tools import run_sql, inspect_schema, manage_memory

        client = OpenAI()
        db = self.db
        tools_spec = _openai_tools_spec()
        messages = [{"role": "system", "content": self._system_prompt}]
        for h in (history or []):
            role = (h.get("role") or "user").lower()
            if role not in ("user", "assistant", "system"):
                role = "user"
            messages.append({"role": role, "content": h.get("content") or ""})
        messages.append({"role": "user", "content": message})

        while True:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=tools_spec,
                tool_choice="auto",
            )
            choice = resp.choices[0] if resp.choices else None
            if not choice:
                return ""
            msg = choice.message
            if msg.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                        }
                        for tc in msg.tool_calls
                    ],
                })
                import json as _json
                for tc in msg.tool_calls:
                    name = tc.function.name
                    args = _json.loads(tc.function.arguments or "{}")
                    if name == "run_sql":
                        content = run_sql(db, args.get("query", ""))
                    elif name == "inspect_schema":
                        content = inspect_schema(db)
                    elif name == "manage_memory":
                        content = manage_memory(
                            db,
                            args.get("action", "get"),
                            args.get("key", ""),
                            args.get("value", ""),
                        )
                    else:
                        content = "{}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": content,
                    })
                continue
            return (msg.content or "").strip()
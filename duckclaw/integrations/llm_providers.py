"""LLM provider factory for DuckClaw agent. Optional deps: langchain-*."""

from __future__ import annotations

import re
from typing import Any, Optional

# Blocklist for read SQL: no DDL or write operations
_READ_BLOCKED = re.compile(
    r"\b(DROP|ALTER|TRUNCATE|CREATE|INSERT|UPDATE|DELETE|ATTACH|COPY|EXPORT|IMPORT|PRAGMA\s+table_info)\b",
    re.IGNORECASE,
)
# Blocklist for write SQL: only allow INSERT/UPDATE/DELETE; block DDL and other writes
_WRITE_BLOCKED = re.compile(
    r"\b(DROP|ALTER|TRUNCATE|CREATE|ATTACH|DETACH|COPY|EXPORT|IMPORT|PRAGMA)\b",
    re.IGNORECASE,
)
# Allowed write statement starters (safe_write policy)
_WRITE_ALLOWED = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE)\s+",
    re.IGNORECASE,
)
# Allowed read statement starters
_READ_ALLOWED = re.compile(
    r"^\s*(SELECT|WITH|SHOW|DESCRIBE)\s",
    re.IGNORECASE,
)


def _safe_table_name(name: str) -> str | None:
    """Return name if it is a safe identifier (alphanumeric + underscore), else None."""
    if not name or not name.strip():
        return None
    n = name.strip()
    if not re.match(r"^[a-zA-Z0-9_]+$", n):
        return None
    return n


def _validate_read_sql(sql: str) -> tuple[bool, str]:
    """Return (True, '') if SQL is allowed for read, else (False, error_message)."""
    s = (sql or "").strip()
    if not s:
        return False, "SQL vacío."
    if _READ_BLOCKED.search(s):
        return False, "Solo se permiten consultas de lectura (SELECT, WITH, SHOW, DESCRIBE). No uses DROP, ALTER, INSERT, etc."
    if not _READ_ALLOWED.search(s):
        return False, "La consulta debe empezar por SELECT, WITH, SHOW o DESCRIBE."
    return True, ""


def _validate_write_sql(sql: str) -> tuple[bool, str]:
    """Return (True, '') if SQL is allowed for safe_write, else (False, error_message)."""
    s = (sql or "").strip()
    if not s:
        return False, "SQL vacío."
    if _WRITE_BLOCKED.search(s):
        return False, "No se permiten DROP, ALTER, TRUNCATE, CREATE, ATTACH, COPY, etc. Solo INSERT, UPDATE, DELETE."
    if not _WRITE_ALLOWED.search(s):
        return False, "La sentencia debe ser INSERT, UPDATE o DELETE."
    return True, ""


def build_duckclaw_tools(db: Any) -> list[Any]:
    """Build LangChain tools for DuckClaw (list_tables, describe_table, run_read_sql, run_write_sql)."""
    from langchain_core.tools import StructuredTool

    def list_tables() -> str:
        """Lista las tablas de la base de datos DuckDB."""
        try:
            return db.query(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            )
        except Exception as e:
            return f"Error: {e}"

    def describe_table(table_name: str) -> str:
        """Describe las columnas de una tabla. table_name: solo letras, números y _."""
        safe = _safe_table_name(table_name)
        if not safe:
            return "Nombre de tabla inválido. Usa solo letras, números y _."
        try:
            return db.query(
                "SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_schema = 'main' AND table_name = '{safe}' ORDER BY ordinal_position"
            )
        except Exception as e:
            return f"Error: {e}"

    def run_read_sql(sql: str) -> str:
        """Ejecuta una consulta de solo lectura (SELECT, WITH, SHOW, DESCRIBE). Devuelve JSON con los resultados."""
        ok, err = _validate_read_sql(sql)
        if not ok:
            return err
        try:
            return db.query(sql)
        except Exception as e:
            from duckclaw.utils import friendly_query_error
            friendly = friendly_query_error(str(e))
            return friendly if friendly else f"Error: {e}"

    def run_write_sql(sql: str) -> str:
        """Ejecuta INSERT, UPDATE o DELETE. No se permiten DROP, ALTER, CREATE, etc."""
        ok, err = _validate_write_sql(sql)
        if not ok:
            return err
        try:
            db.execute(sql)
            return "OK"
        except Exception as e:
            return f"Error: {e}"

    return [
        StructuredTool.from_function(
            func=list_tables,
            name="list_tables",
            description="Lista las tablas de la base de datos DuckDB.",
        ),
        StructuredTool.from_function(
            func=describe_table,
            name="describe_table",
            description="Describe las columnas de una tabla. Argumento: table_name (solo letras, números y _).",
        ),
        StructuredTool.from_function(
            func=run_read_sql,
            name="run_read_sql",
            description="Ejecuta una consulta de solo lectura (SELECT, WITH, SHOW, DESCRIBE). Argumento: sql (cadena SQL).",
        ),
        StructuredTool.from_function(
            func=run_write_sql,
            name="run_write_sql",
            description="Ejecuta INSERT, UPDATE o DELETE. No se permiten DROP, ALTER, CREATE. Argumento: sql (cadena SQL).",
        ),
    ]


def _ensure_url_scheme(url: str) -> str:
    """Prepend http:// if URL has no scheme, so clients accept it."""
    u = (url or "").strip()
    if not u:
        return u
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return "http://" + u


def _mlx_model_id_from_server(base_url: str) -> str | None:
    """GET base_url/models and return the first model id. Returns None on any error."""
    import urllib.request
    url = (base_url or "").rstrip("/") + "/models"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = __import__("json").loads(resp.read().decode())
            models = data.get("data") or []
            if models and isinstance(models[0], dict):
                return (models[0].get("id") or "").strip() or None
    except Exception:
        pass
    return None


def build_llm(
    provider: str,
    model: str = "",
    base_url: str = "",
) -> Any:
    """Build a LangChain chat model from provider/model/base_url. Fail-fast if config missing.

    Returns a BaseChatModel or None for provider 'none_llm'.
    Raises RuntimeError with actionable message if required env/params are missing.
    """
    import os

    provider = (provider or "none_llm").strip().lower()
    if provider == "custom":
        provider = "mlx"
    if provider == "none_llm":
        return None

    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "Proveedor OpenAI requiere OPENAI_API_KEY. "
                "Exporta: export OPENAI_API_KEY='tu-api-key'"
            )
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            raise RuntimeError(
                "Para OpenAI instala: pip install langchain-openai"
            ) from e
        return ChatOpenAI(
            model=model.strip() or "gpt-4o-mini",
            api_key=key,
            temperature=0.2,
        )

    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "Proveedor Anthropic requiere ANTHROPIC_API_KEY. "
                "Exporta: export ANTHROPIC_API_KEY='tu-api-key'"
            )
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as e:
            raise RuntimeError(
                "Para Anthropic instala: pip install langchain-anthropic"
            ) from e
        return ChatAnthropic(
            model=model.strip() or "claude-3-5-haiku-20241022",
            api_key=key,
            temperature=0.2,
        )

    if provider == "ollama":
        url = _ensure_url_scheme(base_url or "http://localhost:11434")
        if not url:
            raise RuntimeError("Proveedor Ollama requiere URL (ej. http://localhost:11434).")
        try:
            from langchain_community.chat_models import ChatOllama
        except ImportError as e:
            raise RuntimeError(
                "Para Ollama instala: pip install langchain-community"
            ) from e
        return ChatOllama(
            base_url=url,
            model=(model or "llama3.2").strip(),
            temperature=0.2,
        )

    if provider == "iotcorelabs":
        url = _ensure_url_scheme(base_url)
        if not url:
            raise RuntimeError("Proveedor IoTCoreLabs requiere URL del endpoint.")
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            raise RuntimeError(
                "Para IoTCoreLabs instala: pip install langchain-openai"
            ) from e
        return ChatOpenAI(
            base_url=url,
            model=(model or "default").strip(),
            api_key=os.environ.get("IOTCORELABS_API_KEY", "dummy").strip(),
            temperature=0.2,
        )

    if provider == "mlx":
        url = _ensure_url_scheme(base_url)
        if not url:
            url = "http://127.0.0.1:8080/v1"
        # Compatibilidad con configuraciones antiguas del wizard (puerto 8000).
        # El servidor MLX de DuckClaw usa 8080 por defecto.
        if ":8000" in url:
            url = url.replace(":8000", ":8080")
        # Always use the model id exposed by the server to avoid HF 401 (config name may be a label like "Slayer-8B-v1.1")
        mod = _mlx_model_id_from_server(url)
        if not mod:
            mod = (model or "").strip() or "default"
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            raise RuntimeError(
                "Para MLX instala: pip install langchain-openai"
            ) from e
        api_key = os.environ.get("MLX_LLM_API_KEY", "not-set").strip()
        return ChatOpenAI(
            base_url=url,
            model=mod,
            api_key=api_key if api_key != "not-set" else "dummy",
            temperature=0.2,
        )

    raise RuntimeError(f"Proveedor desconocido: {provider}")


def _strip_eot(reply: str) -> str:
    """Remove MLM/MLX end-of-sequence tokens from the end of the reply."""
    if not isinstance(reply, str):
        return str(reply)
    for token in ("<|eot_id|>", "<|end|>", "<|end_of_text|>"):
        if reply.endswith(token):
            reply = reply[: -len(token)].strip()
    return reply.strip()


def build_agent_graph(db: Any, llm: Optional[Any] = None) -> Any:
    """Build a LangGraph graph: state has 'incoming', result has 'reply'.

    If llm is None (none_llm), uses DuckClaw memory + rules only.
    If llm is set, uses LLM with DuckClaw tools (list_tables, describe_table, run_read_sql, run_write_sql).
    """
    from langgraph.graph import END, StateGraph

    def reply_from_memory(state: dict) -> dict:
        incoming = (state.get("incoming") or "").strip()
        memory_json = db.query(
            "SELECT text FROM telegram_messages "
            "WHERE text IS NOT NULL AND text != '' "
            "ORDER BY received_at DESC LIMIT 5"
        )
        reply = (
            f"Recibí: {incoming or '(sin texto)'}. "
            f"Contexto reciente en memoria: {memory_json}"
        )
        return {"reply": reply}

    graph = StateGraph(dict)
    if llm is None:
        graph.add_node("respond", reply_from_memory)
        graph.set_entry_point("respond")
        graph.add_edge("respond", END)
        return graph.compile()

    # LLM path: prepare -> agent <-> tools -> set_reply -> END
    tools = build_duckclaw_tools(db)
    llm_with_tools = llm.bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    def prepare_node(state: dict) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage

        incoming = (state.get("incoming") or "").strip()
        memory_json = db.query(
            "SELECT text FROM telegram_messages "
            "WHERE text IS NOT NULL AND text != '' "
            "ORDER BY received_at DESC LIMIT 5"
        )
        system = (
            "Eres un asistente útil. Tienes acceso a una base de datos DuckDB a través de herramientas. "
            "Herramientas: list_tables (listar tablas), describe_table (columnas de una tabla), "
            "run_read_sql (solo SELECT/WITH/SHOW/DESCRIBE), run_write_sql (INSERT/UPDATE/DELETE). "
            "Usa las herramientas cuando el usuario pregunte por datos, tablas o quiera insertar/actualizar/borrar. "
            "Responde de forma breve y clara. Contexto reciente en memoria: " + (memory_json or "[]")
        )
        user_content = f"Mensaje actual: {incoming}"
        return {"messages": [SystemMessage(content=system), HumanMessage(content=user_content)]}

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
        reply = _strip_eot(reply)
        # Si el modelo devolvió un tool call como texto (ej. Slayer-8B sin tool_calls nativos)
        if reply.strip().startswith("{") and '"name"' in reply and ("parameters" in reply or '"args"' in reply):
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

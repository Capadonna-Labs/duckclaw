"""Runnable Telegram bot for third-party interaction with DuckClaw."""

from __future__ import annotations

import asyncio
import os

import core
from core.agents import BicameralOrchestrator, DuckDBNativeEngine
from core.integrations import TelegramBotBase
from core.integrations.llm_providers import build_agent_graph, build_llm


def _normalize_db_path(path: str) -> str:
    """Store relative DB paths under db/ by default."""
    p = (path or "").strip()
    if not p:
        return "db/telegram.duckdb"
    if p == ":memory:":
        return p
    if os.path.isabs(p):
        return p
    if p.startswith("db/"):
        return p
    return f"db/{p}"


class EchoDuckBot(TelegramBotBase):
    """Simple bot that persists updates and responds with a basic echo."""

    def handle_message(self, update):  # type: ignore[override]
        message = getattr(update, "effective_message", None)
        if message is None:
            return

        incoming = getattr(message, "text", None) or getattr(message, "caption", None) or ""
        chat = getattr(message, "chat", None)
        user = getattr(message, "from_user", None)
        chat_id = getattr(chat, "id", None)
        username = getattr(user, "username", None) or getattr(user, "first_name", None) or "unknown"
        print(
            f"[DuckClaw][IN][echo] chat_id={chat_id} user={username} text={incoming!r}",
            flush=True,
        )
        reply = f"DuckClaw registró tu mensaje: {incoming}"
        asyncio.create_task(message.reply_text(reply))
        print(
            f"[DuckClaw][OUT][echo] chat_id={chat_id} reply={reply!r}",
            flush=True,
        )


class LangGraphDuckBot(TelegramBotBase):
    """Bot powered by LangGraph + bicameral memory (OLAP + semantic graph).

    Retrieves structured context from DuckDB (OLAP facts + PGQ relations) before
    each LLM call, injecting it into the graph state so the model can reason over
    persisted knowledge without hallucinating.
    """

    def __init__(
        self,
        db: core.DuckClaw,
        db_path: str = "db/telegram.duckdb",
        provider: str = "none_llm",
        model: str = "",
        base_url: str = "",
    ) -> None:
        super().__init__(db=db)
        self.provider = (provider or "none_llm").strip().lower()
        self.model = (model or "").strip()
        self.base_url = (base_url or "").strip()
        llm = build_llm(self.provider, self.model, self.base_url)
        self.graph = build_agent_graph(db, llm)
        self.engine = DuckDBNativeEngine(db=db, db_path=db_path)
        self.orchestrator = BicameralOrchestrator(engine=self.engine)

    def handle_message(self, update):  # type: ignore[override]
        message = getattr(update, "effective_message", None)
        if message is None:
            return
        incoming = getattr(message, "text", None) or getattr(message, "caption", None) or ""
        chat = getattr(message, "chat", None)
        user = getattr(message, "from_user", None)
        chat_id = getattr(chat, "id", None)
        username = getattr(user, "username", None) or getattr(user, "first_name", None) or "unknown"
        print(
            f"[DuckClaw][IN][langgraph] chat_id={chat_id} user={username} text={incoming!r}",
            flush=True,
        )
        ctx = self.orchestrator.run_query(incoming)
        result = self.graph.invoke({"incoming": incoming, "bicameral_context": ctx.prompt})
        reply = str(result.get("reply") or "LangGraph no generó respuesta.")
        asyncio.create_task(message.reply_text(reply))
        print(
            f"[DuckClaw][OUT][langgraph] chat_id={chat_id} reply={reply!r}",
            flush=True,
        )


class BicameralDuckBot(TelegramBotBase):
    """Bot powered by the bicameral memory orchestrator (DuckDB SQL + PGQ)."""

    def __init__(self, db: core.DuckClaw, db_path: str = "db/telegram.duckdb") -> None:
        super().__init__(db=db)
        self.engine = DuckDBNativeEngine(db=db, db_path=db_path)
        self.orchestrator = BicameralOrchestrator(engine=self.engine)

    @staticmethod
    def _build_reply(result) -> str:
        metadata = getattr(result, "metadata", {}) or {}
        route = metadata.get("route", "hybrid")
        sources = metadata.get("source_ids", [])
        olap = metadata.get("olap", {}) or {}
        semantic = metadata.get("semantic", {}) or {}
        parts = [f"Ruta: {route}", f"Fuentes: {', '.join(str(s) for s in sources if s)}"]
        if olap.get("ok"):
            parts.append(f"OLAP: {olap.get('result', '[]')}")
        else:
            parts.append(f"OLAP error: {olap.get('error', 'desconocido')}")
        if semantic.get("ok"):
            parts.append(f"Grafo: {semantic.get('result', '[]')}")
        else:
            parts.append(f"Grafo error: {semantic.get('error', 'desconocido')}")
        return "\n".join(parts)

    def handle_message(self, update):  # type: ignore[override]
        message = getattr(update, "effective_message", None)
        if message is None:
            return
        incoming = getattr(message, "text", None) or getattr(message, "caption", None) or ""
        chat = getattr(message, "chat", None)
        user = getattr(message, "from_user", None)
        chat_id = getattr(chat, "id", None)
        username = getattr(user, "username", None) or getattr(user, "first_name", None) or "unknown"
        print(
            f"[DuckClaw][IN][bicameral] chat_id={chat_id} user={username} text={incoming!r}",
            flush=True,
        )
        result = self.orchestrator.run_query(incoming)
        reply = self._build_reply(result)
        asyncio.create_task(message.reply_text(reply))
        print(
            f"[DuckClaw][OUT][bicameral] chat_id={chat_id} reply={reply!r}",
            flush=True,
        )


class BicameralLangGraphDuckBot(TelegramBotBase):
    """Bot with bicameral retrieval + LLM answer synthesis."""

    def __init__(
        self,
        db: core.DuckClaw,
        db_path: str = "db/telegram.duckdb",
        provider: str = "none_llm",
        model: str = "",
        base_url: str = "",
    ) -> None:
        super().__init__(db=db)
        self.provider = (provider or "none_llm").strip().lower()
        self.model = (model or "").strip()
        self.base_url = (base_url or "").strip()
        self.llm = build_llm(self.provider, self.model, self.base_url)
        self.engine = DuckDBNativeEngine(db=db, db_path=db_path)
        self.orchestrator = BicameralOrchestrator(engine=self.engine)

    @staticmethod
    def _strip_eot(reply: str) -> str:
        if not isinstance(reply, str):
            return str(reply)
        for token in ("<|eot_id|>", "<|end|>", "<|end_of_text|>"):
            if reply.endswith(token):
                reply = reply[: -len(token)].strip()
        return reply.strip()

    def _generate_reply_with_llm(self, incoming: str, context_prompt: str) -> str:
        if self.llm is None:
            return ""
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            system = (
                "Eres un asistente financiero. Responde en español, claro y breve. "
                "Usa solo el contexto bicameral proporcionado. "
                "Incluye en la respuesta qué fuente usaste (source_ids)."
            )
            user = (
                "Contexto bicameral:\n"
                f"{context_prompt}\n\n"
                f"Pregunta original del usuario:\n{incoming}"
            )
            resp = self.llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
            content = getattr(resp, "content", None) or str(resp)
            return self._strip_eot(content)
        except Exception as e:
            return f"No pude sintetizar con LLM ({e})."

    def handle_message(self, update):  # type: ignore[override]
        message = getattr(update, "effective_message", None)
        if message is None:
            return
        incoming = getattr(message, "text", None) or getattr(message, "caption", None) or ""
        chat = getattr(message, "chat", None)
        user = getattr(message, "from_user", None)
        chat_id = getattr(chat, "id", None)
        username = getattr(user, "username", None) or getattr(user, "first_name", None) or "unknown"
        print(
            f"[DuckClaw][IN][bicameral_langgraph] chat_id={chat_id} user={username} text={incoming!r}",
            flush=True,
        )
        ctx = self.orchestrator.run_query(incoming)
        reply = self._generate_reply_with_llm(incoming, ctx.prompt)
        if not reply:
            reply = BicameralDuckBot._build_reply(ctx)
        asyncio.create_task(message.reply_text(reply))
        print(
            f"[DuckClaw][OUT][bicameral_langgraph] chat_id={chat_id} reply={reply!r}",
            flush=True,
        )


def run_bot(
    token: str,
    db_path: str = "db/telegram.duckdb",
    bot_mode: str = "bicameral",
    llm_provider: str = "",
    llm_model: str = "",
    llm_base_url: str = "",
) -> None:
    """Start Telegram polling bot.

    Modes:
    - bicameral (default): DuckDB native bicameral memory (SQL + PGQ/fallback)
    - echo: simple echo responder
    - langgraph: LLM/tool-based graph with provider/model/base_url
    - bicameral_langgraph: bicameral context + LLM final synthesis
    """
    db_path = _normalize_db_path(db_path)
    if db_path and db_path != ":memory:":
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    db = core.DuckClaw(db_path)

    if bot_mode == "langgraph":
        prov = (llm_provider or "none_llm").strip().lower()
        bot = LangGraphDuckBot(db=db, db_path=db_path, provider=prov, model=llm_model, base_url=llm_base_url)
    elif bot_mode == "bicameral_langgraph":
        prov = (llm_provider or "none_llm").strip().lower()
        bot = BicameralLangGraphDuckBot(
            db=db,
            db_path=db_path,
            provider=prov,
            model=llm_model,
            base_url=llm_base_url,
        )
    elif bot_mode == "echo":
        bot = EchoDuckBot(db=db)
    else:
        bot = BicameralDuckBot(db=db, db_path=db_path)
    app = bot.build_application(token)

    print("Starting Telegram bot (polling)...")
    print(f"DuckClaw DB path: {db_path}")
    print(f"Bot mode: {bot_mode}")
    if bot_mode in ("langgraph", "bicameral_langgraph"):
        prov = getattr(bot, "provider", llm_provider or "none_llm")
        model = getattr(bot, "model", llm_model) or "-"
        print(f"LLM provider: {prov}, model: {model}")
    print("Bot listo. Esperando mensajes en Telegram... (Ctrl+C para salir)")
    # Python 3.14+: get_event_loop() ya no crea loop implícito; crearlo explícitamente
    # para compatibilidad con python-telegram-bot run_polling()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.run_polling()


def _load_dotenv() -> None:
    """Load .env from project root if present (no hard dep on python-dotenv)."""
    env_file = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    env_path = os.path.normpath(env_file)
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


def main() -> None:
    _load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")
    db_path = _normalize_db_path(os.environ.get("DUCKCLAW_DB_PATH", "db/telegram.duckdb"))
    bot_mode = os.environ.get("DUCKCLAW_BOT_MODE", "bicameral").strip().lower() or "bicameral"
    llm_provider = os.environ.get("DUCKCLAW_LLM_PROVIDER", "").strip()
    llm_model = os.environ.get("DUCKCLAW_LLM_MODEL", "").strip()
    llm_base_url = os.environ.get("DUCKCLAW_LLM_BASE_URL", "").strip()
    run_bot(
        token=token,
        db_path=db_path,
        bot_mode=bot_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
    )


if __name__ == "__main__":
    main()

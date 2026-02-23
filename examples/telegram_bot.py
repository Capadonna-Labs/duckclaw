"""Runnable Telegram bot example for third-party interaction with DuckClaw."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

import duckclaw
from duckclaw.integrations import TelegramBotBase
from duckclaw.integrations.llm_providers import build_agent_graph, build_llm


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
    """Bot powered by LangGraph with optional LLM provider (or none_llm: memory + rules)."""

    def __init__(
        self,
        db: duckclaw.DuckClaw,
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
        result = self.graph.invoke({"incoming": incoming})
        reply = str(result.get("reply") or "LangGraph no generó respuesta.")
        asyncio.create_task(message.reply_text(reply))
        print(
            f"[DuckClaw][OUT][langgraph] chat_id={chat_id} reply={reply!r}",
            flush=True,
        )


def run_bot(
    token: str,
    db_path: str = "telegram.duckdb",
    bot_mode: str = "echo",
    llm_provider: str = "",
    llm_model: str = "",
    llm_base_url: str = "",
) -> None:
    """Start Telegram polling bot. For langgraph mode uses llm_provider/model/base_url."""
    if db_path and db_path != ":memory:":
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    db = duckclaw.DuckClaw(db_path)

    if bot_mode == "langgraph":
        prov = (llm_provider or "none_llm").strip().lower()
        bot = LangGraphDuckBot(db=db, provider=prov, model=llm_model, base_url=llm_base_url)
    else:
        bot = EchoDuckBot(db=db)
    app = bot.build_application(token)

    print("Starting Telegram bot (polling)...")
    print(f"DuckClaw DB path: {db_path}")
    print(f"Bot mode: {bot_mode}")
    if bot_mode == "langgraph":
        prov = getattr(bot, "provider", llm_provider or "none_llm")
        model = getattr(bot, "model", llm_model) or "-"
        print(f"LLM provider: {prov}, model: {model}")
    print("Bot listo. Esperando mensajes en Telegram... (Ctrl+C para salir)")
    app.run_polling()


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")
    db_path = os.environ.get("DUCKCLAW_DB_PATH", "telegram.duckdb")
    bot_mode = os.environ.get("DUCKCLAW_BOT_MODE", "echo").strip().lower() or "echo"
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

"""Runnable Telegram bot example for third-party interaction with DuckClaw."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict

# Permitir importar src.agent cuando se ejecuta desde repo root
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_repo_root))

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
    """Bot powered by LangGraph with optional LLM provider (or none_llm: memory + rules).
    Si store_db_path está definido (ruta absoluta a store.duckdb), usa el grafo retail
    (Contador Soberano) y SlayerConsole para resaltar en MAGENTA las consultas DuckClaw."""

    def __init__(
        self,
        db: duckclaw.DuckClaw,
        provider: str = "none_llm",
        model: str = "",
        base_url: str = "",
        store_db_path: str = "",
    ) -> None:
        super().__init__(db=db)
        self.provider = (provider or "none_llm").strip().lower()
        self.model = (model or "").strip()
        self.base_url = (base_url or "").strip()
        llm = build_llm(self.provider, self.model, self.base_url)
        store_abs = (Path(store_db_path).resolve() if store_db_path else None)
        if store_abs and store_abs.exists():
            from duckclaw.utils import SlayerConsole
            from src.agent.router import build_router_graph
            store_db = duckclaw.DuckClaw(str(store_abs))
            self._console = SlayerConsole()
            self.graph = build_router_graph(db, llm, store_db=store_db, console=self._console)
        else:
            self._console = None
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
        # Pasar el texto del usuario al grafo de LangGraph (retail o estándar)
        run_config: Dict[str, Any] = {}
        if os.environ.get("LANGCHAIN_TRACING_V2", "").lower() in ("true", "1"):
            run_config = {
                "tags": ["duckclaw", "telegram", self.provider],
                "run_name": "telegram_langgraph",
            }
        result = self.graph.invoke({"incoming": incoming}, config=run_config)
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
    store_db_path: str = "",
) -> None:
    """Start Telegram polling bot. For langgraph mode uses llm_provider/model/base_url.
    Si store_db_path (ruta absoluta recomendada) está definido, usa el grafo retail y SlayerConsole (MAGENTA)."""
    if bot_mode == "langgraph" and "LANGCHAIN_PROJECT" not in os.environ:
        os.environ.setdefault("LANGCHAIN_PROJECT", "duckclaw")
    # Rutas absolutas para evitar errores en Mac Mini / distintos entornos
    db_path_abs = str(Path(db_path).resolve()) if db_path and db_path != ":memory:" else db_path
    if db_path_abs and db_path_abs != ":memory:":
        Path(db_path_abs).parent.mkdir(parents=True, exist_ok=True)
    db = duckclaw.DuckClaw(db_path_abs)

    store_abs = str(Path(store_db_path).resolve()) if store_db_path else ""
    if bot_mode == "langgraph":
        prov = (llm_provider or "none_llm").strip().lower()
        bot = LangGraphDuckBot(db=db, provider=prov, model=llm_model, base_url=llm_base_url, store_db_path=store_abs)
    else:
        bot = EchoDuckBot(db=db)
    app = bot.build_application(token)

    print("Starting Telegram bot (polling)...")
    print(f"DuckClaw DB path: {db_path_abs}")
    if store_abs:
        print(f"Store DB (retail): {store_abs}")
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
    store_db_path = os.environ.get("DUCKCLAW_STORE_DB_PATH", "").strip()
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
        store_db_path=store_db_path,
    )


if __name__ == "__main__":
    main()

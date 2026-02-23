"""
Bot de Telegram dinámico: configuración desde DuckDB (agent_config) y /setup en caliente.

Uso:
  uv sync --extra agents   # instala telegram + langgraph
  uv run python -m duckclaw.agents.telegram_bot

  # o con pip (en zsh/bash usa comillas):
  pip install 'duckclaw[agents]'
  python -m duckclaw.agents.telegram_bot

Requiere: TELEGRAM_BOT_TOKEN y opcionalmente DUCKCLAW_DB_PATH.
Lee variables desde .env en el directorio actual o en la raíz del proyecto.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Optional

_AGENT_CONFIG_TABLE = "agent_config"


def _load_dotenv() -> None:
    """Carga .env en os.environ si existe (sin dependencia python-dotenv)."""
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent.parent):
        env_file = base / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1].replace('\\"', '"')
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1].replace("\\'", "'")
                        if key:
                            os.environ.setdefault(key, value)
            except Exception:
                pass
            break
_DEFAULT_SYSTEM_PROMPT = "Eres un asistente útil con acceso a una base de datos. Responde de forma breve y clara."
_DEFAULT_FRAMEWORK = "langgraph"


def _log(msg: str) -> None:
    """Write logs unbuffered so PM2 shows them immediately."""
    print(msg, flush=True)


def _get_db_path() -> str:
    path = os.environ.get("DUCKCLAW_DB_PATH", "").strip()
    if path:
        return str(Path(path).resolve())
    return str(Path.cwd() / "duckclaw_agents.duckdb")


def _load_wizard_config() -> dict:
    """Carga la config guardada por la TUI (scripts/install_duckclaw.sh → wizard)."""
    import json
    path = Path.home() / ".config" / "duckclaw" / "wizard_config.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _ensure_agent_config(db: Any) -> None:
    db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_AGENT_CONFIG_TABLE} (
            key VARCHAR PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Valores por defecto si no existen; sembrar llm_* desde wizard si existe
    try:
        import json
        r = db.query(f"SELECT key, value FROM {_AGENT_CONFIG_TABLE}")
        rows = json.loads(r) if isinstance(r, str) else r
        keys_present = {row.get("key") for row in (rows or []) if isinstance(row, dict)}
        defaults = [("framework", _DEFAULT_FRAMEWORK), ("system_prompt", _DEFAULT_SYSTEM_PROMPT)]
        wizard = _load_wizard_config()
        for k, v in wizard.items():
            if k in ("llm_provider", "llm_model", "llm_base_url") and v:
                defaults.append((k, str(v)))
        for k, v in defaults:
            if k not in keys_present:
                esc = str(v).replace("'", "''")[:16384]
                db.execute(
                    f"INSERT INTO {_AGENT_CONFIG_TABLE} (key, value) VALUES ('{k}', '{esc}')"
                )
    except Exception:
        pass


def _get_config(db: Any) -> dict:
    _ensure_agent_config(db)
    import json
    r = db.query(f"SELECT key, value FROM {_AGENT_CONFIG_TABLE}")
    rows = json.loads(r) if isinstance(r, str) else r
    out = {}
    for row in (rows or []):
        if isinstance(row, dict):
            out[row.get("key", "")] = row.get("value", "")
    # Rellenar llm_* desde wizard si no están en agent_config
    wizard = _load_wizard_config()
    for key in ("llm_provider", "llm_model", "llm_base_url"):
        if not out.get(key) and wizard.get(key):
            out[key] = str(wizard[key])
    return out


def _set_config(db: Any, key: str, value: str) -> None:
    _ensure_agent_config(db)
    k = str(key).replace("'", "''")[:128]
    v = str(value).replace("'", "''")[:16384]
    db.execute(
        f"""
        INSERT INTO {_AGENT_CONFIG_TABLE} (key, value) VALUES ('{k}', '{v}')
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """
    )


def _build_adapter(
    db: Any,
    framework: str,
    system_prompt: str,
    llm_provider: str = "",
    llm_model: str = "",
    llm_base_url: str = "",
) -> Any:
    from .adapters.base import BaseAgent
    from .adapters.langgraph_adapter import LangGraphAdapter
    from .adapters.openai_adapter import OpenAIAdapter

    framework = (framework or _DEFAULT_FRAMEWORK).strip().lower()
    provider = (llm_provider or "").strip().lower()
    model = (llm_model or "").strip()
    base_url = (llm_base_url or "").strip()
    if framework == "openai":
        a: BaseAgent = OpenAIAdapter(db, system_prompt=system_prompt)
    else:
        a = LangGraphAdapter(db, system_prompt=system_prompt, provider=provider, model=model, base_url=base_url)
    return a


def _run_bot() -> None:
    _load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        _log("Falta TELEGRAM_BOT_TOKEN. Exporta la variable o ponla en .env en el directorio actual o en la raíz del proyecto.")
        raise SystemExit(1)

    try:
        from telegram.ext import ApplicationBuilder  # noqa: F401
    except ImportError:
        _log("Falta el extra telegram. Instala con:")
        _log("  uv sync --extra agents")
        _log("  # o: pip install 'duckclaw[agents]'   (usa comillas en zsh)")
        raise SystemExit(1)

    from duckclaw import DuckClaw
    from duckclaw.integrations.telegram import TelegramBotBase

    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = DuckClaw(db_path)

    # Persistir mensajes en telegram_messages (tabla estándar)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_messages (
            message_id BIGINT, chat_id BIGINT, user_id BIGINT, username TEXT,
            text TEXT, raw_update_json TEXT, received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    class DynamicAgentBot(TelegramBotBase):
        def handle_message(self, update: Any) -> None:
            message = getattr(update, "effective_message", None)
            if message is None:
                return
            text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
            chat_id = getattr(getattr(message, "chat", None), "id", None)
            user = getattr(message, "from_user", None)
            username = getattr(user, "username", None) or getattr(user, "first_name", None) or "unknown"
            preview = (text[:120] + "...") if len(text) > 120 else text
            _log(f"📩 Mensaje chat={chat_id} user={username}: {preview}")

            # Comando /setup: cambiar system_prompt y framework en caliente
            if text.startswith("/setup"):
                _log("⚙️ Comando /setup recibido")
                self._handle_setup(message, text, chat_id)
                return

            # Cargar config desde agent_config (y wizard si falta llm_*)
            config = _get_config(self.db)
            system_prompt = config.get("system_prompt") or _DEFAULT_SYSTEM_PROMPT
            framework = config.get("framework") or _DEFAULT_FRAMEWORK
            llm_provider = config.get("llm_provider") or ""
            llm_model = config.get("llm_model") or ""
            llm_base_url = config.get("llm_base_url") or ""

            t0 = time.perf_counter()
            try:
                adapter = _build_adapter(
                    self.db, framework, system_prompt,
                    llm_provider=llm_provider, llm_model=llm_model, llm_base_url=llm_base_url,
                )
                history = self._get_history(chat_id, limit=10)
                reply = adapter.invoke(text, history=history)
            except RuntimeError as e:
                reply = str(e)
            except Exception as e:
                reply = f"Error del agente: {e}"
                import traceback
                traceback.print_exc()
            from duckclaw.integrations.llm_providers import _strip_eot
            reply = _strip_eot(str(reply)) if reply else ""
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            reply_preview = (reply[:160] + "...") if len(reply) > 160 else reply
            _log(f"📤 Respuesta chat={chat_id} ({elapsed_ms} ms): {reply_preview}")
            asyncio.create_task(message.reply_text(reply or "Sin respuesta."))

        def _handle_setup(self, message: Any, text: str, chat_id: Any) -> None:
            # /setup framework=openai
            # /setup system_prompt=Eres un experto en SQL.
            parts = text.split(maxsplit=1)
            body = (parts[1] if len(parts) > 1 else "").strip()
            if not body:
                config = _get_config(self.db)
                asyncio.create_task(
                    message.reply_text(
                        f"Config actual:\nframework={config.get('framework', _DEFAULT_FRAMEWORK)}\n"
                        f"llm_provider={config.get('llm_provider', '')}\n"
                        f"llm_model={config.get('llm_model', '')}\n"
                        f"system_prompt={config.get('system_prompt', '')[:150]}...\n\n"
                        "Para cambiar: /setup framework=langgraph | llm_provider=openai | system_prompt=..."
                    )
                )
                return
            if "=" in body:
                key, _, value = body.partition("=")
                key = key.strip().lower()
                value = value.strip()
                allowed = ("framework", "system_prompt", "llm_provider", "llm_model", "llm_base_url")
                if key in allowed:
                    _set_config(self.db, key, value)
                    asyncio.create_task(message.reply_text(f"Config actualizado: {key}={value[:80]}..."))
                else:
                    asyncio.create_task(message.reply_text(f"Claves permitidas: {', '.join(allowed)}"))
            else:
                asyncio.create_task(message.reply_text("Uso: /setup framework=openai o /setup system_prompt=..."))

        def _get_history(self, chat_id: Any, limit: int = 10) -> list:
            import json
            try:
                r = self.db.query(
                    f"SELECT text FROM telegram_messages WHERE chat_id = {int(chat_id)} ORDER BY received_at DESC LIMIT {limit * 2}"
                )
                rows = json.loads(r) if isinstance(r, str) else []
                out = []
                for row in reversed((rows or [])[: limit * 2]):
                    t = row.get("text") if isinstance(row, dict) else None
                    if t and str(t).strip() and not str(t).startswith("/"):
                        out.append({"role": "user", "content": str(t)})
                return out[-limit:]  # últimos N mensajes usuario
            except Exception:
                return []

    bot = DynamicAgentBot(db=db)
    app = bot.build_application(token)

    from telegram import error as tg_error

    def _error_handler(update: Any, context: Any) -> None:
        err = getattr(context, "error", None)
        if isinstance(err, tg_error.Conflict):
            _log(
                "Conflict: otra instancia del bot está usando el mismo token (p. ej. con PM2). "
                "Detén la otra instancia o no arranques este proceso. Salida con código 0 para evitar reinicio en bucle."
            )
            raise SystemExit(0)
        if err:
            raise err

    app.add_error_handler(_error_handler)
    _log("Bot dinámico DuckClaw agents. Comando /setup para cambiar framework y system_prompt en caliente.")
    _log(f"DB: {db_path}")
    _log("🎧 Escuchando mensajes en Telegram... (Ctrl+C para salir)")
    app.run_polling()


if __name__ == "__main__":
    # Python 3.10+: el main thread ya no tiene event loop por defecto; run_polling() lo necesita
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    _run_bot()

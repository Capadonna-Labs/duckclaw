"""Telegram integration utilities for DuckClaw.

This module keeps Telegram dependencies optional. Importing this file does not
require `python-telegram-bot`; only runtime helpers that build a bot app do.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Optional, TYPE_CHECKING

from .. import DuckClaw

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import Application


class TelegramBotBase(ABC):
    """Base class for Telegram bots with automatic DuckClaw persistence.

    Every incoming message/update passed to `process_update()` is persisted into
    DuckClaw before custom bot logic executes.
    """

    def __init__(self, db: DuckClaw, table_name: str = "telegram_messages") -> None:
        self.db = db
        self.table_name = table_name
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                message_id BIGINT,
                chat_id BIGINT,
                user_id BIGINT,
                username TEXT,
                text TEXT,
                raw_update_json TEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    @staticmethod
    def _sql_literal(value: Optional[Any]) -> str:
        if value is None:
            return "NULL"
        text = str(value).replace("'", "''")
        return f"'{text}'"

    @staticmethod
    def _update_to_json(update: Any) -> str:
        if hasattr(update, "to_dict"):
            payload = update.to_dict()
        elif isinstance(update, dict):
            payload = update
        else:
            payload = {"repr": repr(update)}
        return json.dumps(payload, ensure_ascii=False)

    def persist_update(self, update: Any) -> None:
        """Persist one Telegram update/message into DuckClaw."""
        message = getattr(update, "effective_message", None) or getattr(update, "message", None)
        chat = getattr(message, "chat", None) if message is not None else None
        user = getattr(message, "from_user", None) if message is not None else None

        message_id = getattr(message, "message_id", None)
        chat_id = getattr(chat, "id", None)
        user_id = getattr(user, "id", None)
        username = getattr(user, "username", None)
        text = None
        if message is not None:
            text = getattr(message, "text", None) or getattr(message, "caption", None)

        raw_json = self._update_to_json(update)

        self.db.execute(
            f"""
            INSERT INTO {self.table_name} (
                message_id, chat_id, user_id, username, text, raw_update_json
            ) VALUES (
                {self._sql_literal(message_id)},
                {self._sql_literal(chat_id)},
                {self._sql_literal(user_id)},
                {self._sql_literal(username)},
                {self._sql_literal(text)},
                {self._sql_literal(raw_json)}
            )
            """
        )

    def process_update(self, update: Any) -> None:
        """Persist first, then delegate to the subclass business logic."""
        self.persist_update(update)
        self.handle_message(update)

    @abstractmethod
    def handle_message(self, update: Any) -> None:
        """Implement bot-specific behavior after persistence."""
        raise NotImplementedError

    def build_application(self, token: str) -> "Application":
        """Optional helper to create a polling app with python-telegram-bot.

        Raises:
            ImportError: If `python-telegram-bot` is not installed.
        """
        try:
            from telegram.ext import ApplicationBuilder, MessageHandler, filters
        except ImportError as exc:
            raise ImportError(
                "Telegram integration requires optional dependency "
                "`python-telegram-bot`. Install with: pip install 'duckclaw[telegram]'"
            ) from exc

        app = ApplicationBuilder().token(token).build()
        app.add_handler(MessageHandler(filters.ALL, self._on_update))
        return app

    async def _on_update(self, update: "Update", _context: Any) -> None:
        self.process_update(update)

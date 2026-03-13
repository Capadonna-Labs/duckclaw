"""Tests for /forget when called via API gateway (session_id) vs Telegram (chat_id)."""

from __future__ import annotations

from unittest.mock import MagicMock

from duckclaw.agents.on_the_fly_commands import execute_forget


def _mock_db() -> MagicMock:
    """Minimal db mock with execute/query for on_the_fly_commands."""
    db = MagicMock()
    db.query.return_value = "[]"
    return db


def test_forget_via_api_with_session_id_default_succeeds() -> None:
    """Fix: /forget via API with session_id='default' succeeds and deletes api_conversation."""
    db = _mock_db()
    result = execute_forget(db, "default")
    assert "✅" in result
    assert "Error" not in result
    call_args = [str(c) for c in db.execute.call_args_list]
    assert any("api_conversation" in a for a in call_args)


def test_forget_via_telegram_deletes_telegram_conversation() -> None:
    """Telegram: numeric chat_id deletes telegram_conversation."""
    db = _mock_db()
    result = execute_forget(db, "12345")
    assert "✅" in result
    call_args = [str(c) for c in db.execute.call_args_list]
    assert any("telegram_conversation" in a for a in call_args)

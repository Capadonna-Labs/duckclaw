"""Tests for duckclaw.agents.on_the_fly_commands."""

from __future__ import annotations

import duckclaw
from duckclaw.agents.on_the_fly_commands import (
    parse_command,
    handle_command,
    get_chat_state,
    set_chat_state,
    execute_forget,
    execute_context_toggle,
    execute_health,
    execute_audit,
    execute_skills_list,
    execute_approve_reject,
    get_history_limit_for_chat,
    get_worker_id_for_chat,
    save_last_audit,
)


def _make_db() -> duckclaw.DuckClaw:
    db = duckclaw.DuckClaw(":memory:")
    db.execute("""
        CREATE TABLE IF NOT EXISTS telegram_conversation (
            chat_id BIGINT, role TEXT, content TEXT,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    return db


class TestParseCommand:
    def test_slash_command(self) -> None:
        assert parse_command("/role finanz") == ("role", "finanz")

    def test_command_no_args(self) -> None:
        assert parse_command("/skills") == ("skills", "")

    def test_not_a_command(self) -> None:
        assert parse_command("hello world") == ("", "")

    def test_empty(self) -> None:
        assert parse_command("") == ("", "")

    def test_case_insensitive(self) -> None:
        name, args = parse_command("/FORGET")
        assert name == "forget"


class TestChatState:
    def test_set_and_get(self) -> None:
        db = _make_db()
        set_chat_state(db, 123, "theme", "dark")
        assert get_chat_state(db, 123, "theme") == "dark"

    def test_get_missing_returns_empty(self) -> None:
        db = _make_db()
        assert get_chat_state(db, 999, "nonexistent") == ""

    def test_overwrite(self) -> None:
        db = _make_db()
        set_chat_state(db, 1, "k", "v1")
        set_chat_state(db, 1, "k", "v2")
        assert get_chat_state(db, 1, "k") == "v2"

    def test_escaping(self) -> None:
        db = _make_db()
        set_chat_state(db, 1, "key", "it's a test")
        assert get_chat_state(db, 1, "key") == "it's a test"


class TestExecuteForget:
    def test_clears_conversation(self) -> None:
        db = _make_db()
        db.execute("INSERT INTO telegram_conversation (chat_id, role, content) VALUES (42, 'user', 'hi')")
        result = execute_forget(db, 42)
        assert "borrado" in result.lower() or "✅" in result


class TestExecuteContextToggle:
    def test_on(self) -> None:
        db = _make_db()
        result = execute_context_toggle(db, 1, "on")
        assert "activado" in result.lower()
        assert get_chat_state(db, 1, "use_rag") == "true"

    def test_off(self) -> None:
        db = _make_db()
        result = execute_context_toggle(db, 1, "off")
        assert "desactivado" in result.lower()
        assert get_chat_state(db, 1, "use_rag") == "false"

    def test_empty_shows_status(self) -> None:
        db = _make_db()
        result = execute_context_toggle(db, 1, "")
        assert "uso" in result.lower() or "estado" in result.lower()


class TestExecuteHealth:
    def test_duckdb_ok(self) -> None:
        db = _make_db()
        result = execute_health(db)
        assert "DuckDB" in result
        assert "conectado" in result or "✅" in result


class TestExecuteAudit:
    def test_no_audit_data(self) -> None:
        db = _make_db()
        result = execute_audit(db, 1)
        assert "no hay" in result.lower() or "evidencia" in result.lower()

    def test_with_audit_data(self) -> None:
        db = _make_db()
        save_last_audit(db, 1, latency_ms=42, sql="SELECT 1", run_id="abc")
        result = execute_audit(db, 1)
        assert "42" in result
        assert "SELECT 1" in result


class TestExecuteSkillsList:
    def test_default_skills(self) -> None:
        db = _make_db()
        result = execute_skills_list(db, 1)
        assert "run_sql" in result


class TestExecuteApproveReject:
    def test_no_pending(self) -> None:
        db = _make_db()
        result = execute_approve_reject(db, 1, True)
        assert "pendiente" in result.lower() or "no hay" in result.lower()


class TestGetHistoryLimit:
    def test_default(self) -> None:
        db = _make_db()
        assert get_history_limit_for_chat(db, 1) == 10

    def test_rag_off(self) -> None:
        db = _make_db()
        set_chat_state(db, 1, "use_rag", "false")
        assert get_history_limit_for_chat(db, 1) == 3


class TestGetWorkerIdForChat:
    def test_no_worker(self) -> None:
        db = _make_db()
        assert get_worker_id_for_chat(db, 1) == ""

    def test_with_worker(self) -> None:
        db = _make_db()
        set_chat_state(db, 1, "worker_id", "finanz")
        assert get_worker_id_for_chat(db, 1) == "finanz"


class TestHandleCommand:
    def test_non_command_returns_none(self) -> None:
        db = _make_db()
        assert handle_command(db, 1, "hello") is None

    def test_forget_command(self) -> None:
        db = _make_db()
        result = handle_command(db, 1, "/forget")
        assert result is not None
        assert "✅" in result

    def test_context_on(self) -> None:
        db = _make_db()
        result = handle_command(db, 1, "/context on")
        assert result is not None
        assert "activado" in result.lower()

    def test_health(self) -> None:
        db = _make_db()
        result = handle_command(db, 1, "/health")
        assert result is not None
        assert "DuckDB" in result

    def test_skills(self) -> None:
        db = _make_db()
        result = handle_command(db, 1, "/skills")
        assert result is not None
        assert "run_sql" in result

    def test_unknown_command(self) -> None:
        db = _make_db()
        assert handle_command(db, 1, "/nonexistent") is None

"""Tests for /role command and effective_worker_id in API gateway."""

from __future__ import annotations

from pathlib import Path

import pytest

from duckclaw.agents.on_the_fly_commands import (
    execute_role_switch,
    get_worker_id_for_chat,
    handle_command,
    set_chat_state,
)
from duckclaw.workers.factory import list_workers


@pytest.fixture
def db():
    """Real DuckDB for integration test (uses gateway.duckdb)."""
    from duckclaw import DuckClaw

    path = Path(__file__).resolve().parent.parent / "db" / "gateway.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    return DuckClaw(str(path))


def test_role_switch_stores_worker_id(db) -> None:
    """/role finanz stores worker_id in agent_config."""
    chat_id = "test_role_123"
    # Limpiar estado previo
    set_chat_state(db, chat_id, "worker_id", "")
    assert get_worker_id_for_chat(db, chat_id) == ""

    reply = execute_role_switch(db, chat_id, "finanz")
    assert "finanz" in reply.lower()
    assert "✅" in reply
    assert get_worker_id_for_chat(db, chat_id) == "finanz"


def test_role_switch_to_another_worker(db) -> None:
    """/role research_worker overwrites previous worker_id."""
    chat_id = "test_role_456"
    set_chat_state(db, chat_id, "worker_id", "finanz")

    reply = execute_role_switch(db, chat_id, "research_worker")
    assert "research_worker" in reply.lower()
    assert get_worker_id_for_chat(db, chat_id) == "research_worker"


def test_role_unknown_worker_rejects(db) -> None:
    """/role unknown_xyz returns error and does not change state."""
    chat_id = "test_role_789"
    set_chat_state(db, chat_id, "worker_id", "finanz")

    reply = execute_role_switch(db, chat_id, "unknown_xyz_123")
    assert "desconocido" in reply.lower() or "plantillas" in reply.lower()
    assert get_worker_id_for_chat(db, chat_id) == "finanz"


def test_handle_command_processes_role(db) -> None:
    """handle_command processes /role and returns reply."""
    chat_id = "test_role_cmd"
    set_chat_state(db, chat_id, "worker_id", "")

    reply = handle_command(db, chat_id, "/role finanz")
    assert reply is not None
    assert "finanz" in (reply or "").lower()
    assert get_worker_id_for_chat(db, chat_id) == "finanz"


def test_role_no_args_shows_usage(db) -> None:
    """/role without args shows usage and available workers."""
    chat_id = "test_role_usage"
    reply = execute_role_switch(db, chat_id, "")
    assert "Uso" in reply or "role" in reply.lower()
    available = list_workers()
    if available:
        assert any(w in reply for w in available)

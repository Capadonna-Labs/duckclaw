"""Tests for the Agent Activity Manager and its API endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import time
from unittest import mock

import pytest

from duckclaw.api.activity import (
    ActivityManager,
    AgentState,
    AgentStatus,
    InMemoryBackend,
    HEARTBEAT_TIMEOUT_S,
)


# ── Unit tests: state machine ────────────────────────────────────────────────


class TestAgentStateMachine:
    def test_initial_state_is_idle(self) -> None:
        mgr = ActivityManager()
        state = mgr.get_status("finanz")
        assert state.status == AgentStatus.IDLE

    def test_mark_busy(self) -> None:
        mgr = ActivityManager()
        state = mgr.mark_busy("finanz", task_description="Analizando factura")
        assert state.status == AgentStatus.BUSY
        assert state.task_description == "Analizando factura"
        assert state.task_id is not None
        assert state.since is not None

    def test_mark_idle_after_busy(self) -> None:
        mgr = ActivityManager()
        mgr.mark_busy("finanz")
        state = mgr.mark_idle("finanz")
        assert state.status == AgentStatus.IDLE
        assert state.task_id is None

    def test_mark_waiting(self) -> None:
        mgr = ActivityManager()
        mgr.mark_busy("support", task_description="Procesando ticket")
        state = mgr.mark_waiting("support")
        assert state.status == AgentStatus.WAITING
        assert state.task_description == "Procesando ticket"

    def test_mark_error(self) -> None:
        mgr = ActivityManager()
        state = mgr.mark_error("finanz", detail="LLM timeout")
        assert state.status == AgentStatus.ERROR
        assert state.task_description == "LLM timeout"

    def test_is_busy(self) -> None:
        mgr = ActivityManager()
        assert not mgr.is_busy("finanz")
        mgr.mark_busy("finanz")
        assert mgr.is_busy("finanz")
        mgr.mark_idle("finanz")
        assert not mgr.is_busy("finanz")


class TestHeartbeat:
    def test_heartbeat_updates_timestamp(self) -> None:
        mgr = ActivityManager()
        mgr.mark_busy("finanz")
        state_before = mgr.get_status("finanz")
        hb_before = state_before.last_heartbeat

        time.sleep(0.01)
        ok = mgr.heartbeat("finanz")
        assert ok

        state_after = mgr.get_status("finanz")
        assert state_after.last_heartbeat is not None
        assert state_after.last_heartbeat > (hb_before or 0)

    def test_heartbeat_idle_returns_false(self) -> None:
        mgr = ActivityManager()
        assert not mgr.heartbeat("finanz")


class TestGetAllStatuses:
    def test_multiple_workers(self) -> None:
        mgr = ActivityManager()
        mgr.mark_busy("finanz", task_description="Factura")
        mgr.mark_idle("support")
        mgr.mark_waiting("research")

        all_statuses = mgr.get_all_statuses()
        assert all_statuses["finanz"]["status"] == "BUSY"
        assert all_statuses["finanz"]["task"] == "Factura"
        assert all_statuses["support"]["status"] == "IDLE"
        assert all_statuses["research"]["status"] == "WAITING"

    def test_empty_registry(self) -> None:
        mgr = ActivityManager()
        assert mgr.get_all_statuses() == {}


class TestZombieDetection:
    def test_detects_zombie(self) -> None:
        mgr = ActivityManager()
        state = mgr.mark_busy("finanz")
        state.last_heartbeat = time.monotonic() - HEARTBEAT_TIMEOUT_S - 10
        mgr._backend.set_state(state)

        released = mgr.check_zombies()
        assert "finanz" in released
        assert mgr.get_status("finanz").status == AgentStatus.ERROR

    def test_healthy_worker_not_released(self) -> None:
        mgr = ActivityManager()
        mgr.mark_busy("finanz")
        released = mgr.check_zombies()
        assert released == []
        assert mgr.get_status("finanz").status == AgentStatus.BUSY


class TestSSEBroadcast:
    def test_subscriber_receives_events(self) -> None:
        mgr = ActivityManager()
        q = mgr.subscribe()

        mgr.mark_busy("finanz", task_description="Test task")
        assert not q.empty()

        event = q.get_nowait()
        assert event["worker_id"] == "finanz"
        assert event["status"] == "BUSY"
        assert event["task"] == "Test task"

        mgr.unsubscribe(q)

    def test_unsubscribed_queue_no_events(self) -> None:
        mgr = ActivityManager()
        q = mgr.subscribe()
        mgr.unsubscribe(q)

        mgr.mark_busy("finanz")
        assert q.empty()


class TestAgentStateToDict:
    def test_serialization(self) -> None:
        state = AgentState(
            worker_id="finanz",
            status=AgentStatus.BUSY,
            task_id="t1",
            task_description="Analizando",
            since="2026-03-10T09:30:00+00:00",
        )
        d = state.to_dict()
        assert d == {
            "status": "BUSY",
            "task": "Analizando",
            "task_id": "t1",
            "since": "2026-03-10T09:30:00+00:00",
        }

    def test_idle_serialization(self) -> None:
        state = AgentState(worker_id="support")
        d = state.to_dict()
        assert d["status"] == "IDLE"
        assert d["task"] is None
        assert d["task_id"] is None


# ── Integration tests: API endpoints ─────────────────────────────────────────

os.environ.setdefault("DUCKCLAW_TAILSCALE_AUTH_KEY", "test-key-for-tests")

from fastapi.testclient import TestClient
from duckclaw.api.gateway import app

_AUTH = {"X-Tailscale-Auth-Key": "test-key-for-tests"}


@pytest.fixture
def client() -> TestClient:
    # Reset the activity manager singleton for test isolation
    import duckclaw.api.activity as act_mod
    act_mod._manager = None
    return TestClient(app, headers=_AUTH)


class TestActivityEndpoints:
    def test_get_all_empty(self, client: TestClient) -> None:
        r = client.get("/api/v1/agents/status")
        assert r.status_code == 200
        assert r.json() == {}

    def test_get_single_default_idle(self, client: TestClient) -> None:
        r = client.get("/api/v1/agents/status/finanz")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "IDLE"

    def test_get_single_invalid_worker_id(self, client: TestClient) -> None:
        r = client.get("/api/v1/agents/status/bad;id")
        assert r.status_code == 400

    def test_heartbeat_idle_fails(self, client: TestClient) -> None:
        r = client.post("/api/v1/agents/finanz/heartbeat")
        assert r.status_code == 409

    def test_heartbeat_busy_succeeds(self, client: TestClient) -> None:
        from duckclaw.api.activity import get_activity_manager
        mgr = get_activity_manager()
        mgr.mark_busy("finanz")

        r = client.post("/api/v1/agents/finanz/heartbeat")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_status_after_transitions(self, client: TestClient) -> None:
        from duckclaw.api.activity import get_activity_manager
        mgr = get_activity_manager()

        mgr.mark_busy("finanz", task_description="Factura Q1")
        mgr.mark_idle("support")

        r = client.get("/api/v1/agents/status")
        assert r.status_code == 200
        data = r.json()
        assert data["finanz"]["status"] == "BUSY"
        assert data["finanz"]["task"] == "Factura Q1"
        assert data["support"]["status"] == "IDLE"


class TestChatBusyGuard:
    def test_chat_returns_202_when_busy(self, client: TestClient) -> None:
        from duckclaw.api.activity import get_activity_manager
        mgr = get_activity_manager()
        mgr.mark_busy("finanz", task_description="Tarea previa")

        r = client.post(
            "/api/v1/agent/finanz/chat",
            json={"message": "hola", "stream": False},
        )
        assert r.status_code == 202
        data = r.json()
        assert data["status"] == "BUSY"
        assert "procesando" in data["message"].lower()

    def test_root_includes_activity_endpoints(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        endpoints = r.json().get("endpoints", [])
        assert "/api/v1/agents/status" in endpoints
        assert "/api/v1/agents/activity-stream" in endpoints

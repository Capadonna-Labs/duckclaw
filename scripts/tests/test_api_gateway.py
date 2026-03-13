"""Tests for DuckClaw API Gateway."""

from __future__ import annotations

import os

# Set auth key before app loads so middleware accepts test requests
os.environ.setdefault("DUCKCLAW_TAILSCALE_AUTH_KEY", "test-key-for-tests")

import pytest
from fastapi.testclient import TestClient

from duckclaw.api.gateway import app

_AUTH_HEADERS = {"X-Tailscale-Auth-Key": "test-key-for-tests"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, headers=_AUTH_HEADERS)


def test_root(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data.get("service") == "DuckClaw API Gateway"
    assert "endpoints" in data


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_system_health(client: TestClient) -> None:
    r = client.get("/api/v1/system/health")
    assert r.status_code == 200
    data = r.json()
    assert "tailscale" in data
    assert "duckdb" in data
    assert "mlx" in data


def test_homeostasis_status(client: TestClient) -> None:
    r = client.get("/api/v1/homeostasis/status")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_homeostasis_ask_task(client: TestClient) -> None:
    r = client.post("/api/v1/homeostasis/ask_task", json={})
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("trigger") == "timer"


def test_homeostasis_ask_task_with_objectives(client: TestClient) -> None:
    r = client.post(
        "/api/v1/homeostasis/ask_task",
        json={"suggested_objectives": ["Aumentar ventas", "Disminuir tiempo de respuesta"]},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_agent_history_requires_session(client: TestClient) -> None:
    r = client.get("/api/v1/agent/finanz/history?session_id=s1")
    assert r.status_code == 200
    data = r.json()
    assert "history" in data
    assert data.get("worker_id") == "finanz"


def test_agent_workers_list(client: TestClient) -> None:
    r = client.get("/api/v1/agent/workers")
    assert r.status_code == 200
    data = r.json()
    assert "workers" in data
    assert isinstance(data["workers"], list)
    assert "finanz" in data["workers"]


def test_forget_command_via_api_succeeds(client: TestClient) -> None:
    """POST /forget with session_id='default' succeeds (fix for API gateway bug)."""
    r = client.post(
        "/api/v1/agent/finanz/chat",
        json={"message": "/forget", "session_id": "default", "stream": False},
    )
    assert r.status_code == 200
    data = r.json()
    assert "response" in data
    assert "✅" in data["response"] or "Historial borrado" in data["response"]

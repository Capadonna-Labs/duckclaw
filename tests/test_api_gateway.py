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


def test_agent_history_requires_session(client: TestClient) -> None:
    r = client.get("/api/v1/agent/personal_finance/history?session_id=s1")
    assert r.status_code == 200
    data = r.json()
    assert "history" in data
    assert data.get("worker_id") == "personal_finance"

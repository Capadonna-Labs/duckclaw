"""Equipo efectivo: chat > tenant > env > list_workers (manager /workers)."""

from __future__ import annotations

from pathlib import Path

import pytest

from duckclaw import DuckClaw
from duckclaw.graphs.on_the_fly_commands import (
    _upsert_authorized_user,
    execute_team,
    get_effective_team_templates,
    get_team_templates,
    get_tenant_team_templates,
    set_team_templates,
    set_tenant_team_templates,
)
from duckclaw.workers.factory import list_workers


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "team_effective.duckdb")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return DuckClaw(path)


def test_get_effective_chat_overrides_tenant(db) -> None:
    all_w = list_workers()
    if len(all_w) < 2:
        pytest.skip("need at least 2 worker templates")
    first, second = all_w[0], all_w[1]
    tid = "tenant_x"
    set_tenant_team_templates(db, tid, [second])
    set_team_templates(db, "chat_a", [first])
    eff = get_effective_team_templates(db, "chat_a", tid, None)
    assert eff == [first]


def test_get_effective_tenant_when_chat_unset(db) -> None:
    all_w = list_workers()
    if not all_w:
        pytest.skip("need worker templates")
    only = [all_w[0]]
    tid = "tenant_y"
    set_tenant_team_templates(db, tid, only)
    assert get_team_templates(db, "other_user_dm") == []
    eff = get_effective_team_templates(db, "other_user_dm", tid, None)
    assert eff == only


def test_get_effective_env_fallback(monkeypatch, db) -> None:
    all_w = list_workers()
    if not all_w:
        pytest.skip("need worker templates")
    target = all_w[0]
    monkeypatch.setenv("DUCKCLAW_GATEWAY_TEAM_TEMPLATES", target)
    eff = get_effective_team_templates(db, "no_config_chat", "default", None)
    assert eff == [target]


def test_execute_team_admin_syncs_tenant(db) -> None:
    all_w = list_workers()
    if not all_w:
        pytest.skip("need worker templates")
    wid = all_w[0]
    tid = "tenant_z"
    admin_id = "999001"
    _upsert_authorized_user(db, tenant_id=tid, user_id=admin_id, username="admin", role="admin")
    execute_team(db, "admin_chat", wid, tenant_id=tid, requester_id=admin_id)
    assert get_team_templates(db, "admin_chat") == [wid]
    assert get_tenant_team_templates(db, tid) == [wid]

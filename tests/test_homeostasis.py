"""Tests for homeostasis (Active Inference Framework)."""

from __future__ import annotations

import json

import duckclaw
import pytest

from duckclaw.forge.homeostasis import (
    BeliefRegistry,
    compute_surprise,
    load_beliefs_from_config,
    SurpriseCalculator,
)
from duckclaw.forge.homeostasis.surprise import SurpriseResult


def test_compute_surprise_no_anomaly() -> None:
    """Delta within threshold -> no anomaly."""
    r = compute_surprise(observed=0.88, target=0.90, threshold=0.05)
    assert isinstance(r, SurpriseResult)
    assert r.delta == pytest.approx(0.02)
    assert r.is_anomaly is False
    assert r.target == 0.90
    assert r.observed == 0.88


def test_compute_surprise_anomaly() -> None:
    """Delta exceeds threshold -> anomaly."""
    r = compute_surprise(observed=0.80, target=0.90, threshold=0.05)
    assert r.delta == pytest.approx(0.10)
    assert r.is_anomaly is True


def test_compute_surprise_exact_threshold() -> None:
    """Delta equals threshold -> no anomaly (strict >). Use exact values to avoid float precision."""
    r = compute_surprise(observed=5.0, target=10.0, threshold=5.0)
    assert r.delta == 5.0
    assert r.is_anomaly is False


def test_surprise_calculator_compute() -> None:
    """SurpriseCalculator.compute is alias for compute_surprise."""
    r = SurpriseCalculator.compute(5.0, 5.0, 1.0)
    assert r.delta == 0.0
    assert r.is_anomaly is False


def test_load_beliefs_from_config_empty() -> None:
    """Empty or None config returns empty lists."""
    beliefs, actions = load_beliefs_from_config(None)
    assert beliefs == []
    assert actions == {}

    beliefs, actions = load_beliefs_from_config({})
    assert beliefs == []
    assert actions == {}


def test_load_beliefs_from_config_valid() -> None:
    """Valid config parses beliefs and actions."""
    config = {
        "beliefs": [
            {"key": "test_coverage", "target": 0.90, "threshold": 0.05},
            {"key": "presupuesto", "target": 5000.0, "threshold": 500.0},
        ],
        "actions": [
            {"trigger": "test_coverage_drop", "skill": "github_create_issue", "message": "Cobertura baja."},
        ],
    }
    beliefs, actions = load_beliefs_from_config(config)
    assert len(beliefs) == 2
    assert beliefs[0].key == "test_coverage"
    assert beliefs[0].target == 0.90
    assert beliefs[0].threshold == 0.05
    assert len(actions) == 1
    assert "test_coverage_drop" in actions
    assert actions["test_coverage_drop"].skill == "github_create_issue"


def test_belief_registry_from_config() -> None:
    """BeliefRegistry.from_config creates registry."""
    config = {"beliefs": [{"key": "x", "target": 1.0, "threshold": 0.1}], "actions": []}
    reg = BeliefRegistry.from_config(config)
    assert reg.get_belief("x") is not None
    assert reg.get_belief("x").target == 1.0
    assert reg.get_belief("y") is None


def test_belief_registry_trigger_for_belief() -> None:
    """trigger_for_belief generates expected trigger names."""
    reg = BeliefRegistry.from_config({"beliefs": [], "actions": []})
    assert reg.trigger_for_belief("test_coverage", is_drop=True) == "test_coverage_drop"
    assert reg.trigger_for_belief("test_coverage", is_drop=False) == "test_coverage_breach"


def test_homeostasis_manager_maintain() -> None:
    """HomeostasisManager.check returns maintain when within threshold."""
    db = duckclaw.DuckClaw(":memory:")
    db.execute("CREATE SCHEMA IF NOT EXISTS test_worker")
    db.execute("""
        CREATE TABLE IF NOT EXISTS test_worker.agent_beliefs (
            belief_key VARCHAR PRIMARY KEY,
            target_value REAL NOT NULL,
            observed_value REAL,
            threshold REAL NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    config = {"beliefs": [{"key": "presupuesto", "target": 5000.0, "threshold": 500.0}], "actions": []}
    from duckclaw.forge.homeostasis import HomeostasisManager

    reg = BeliefRegistry.from_config(config)
    mgr = HomeostasisManager(db=db, schema="test_worker", registry=reg)
    plan = mgr.check("presupuesto", 4800.0, auto_update=True)
    assert plan["action"] == "maintain"
    assert "presupuesto" in plan["belief_key"]


def test_homeostasis_manager_restore() -> None:
    """HomeostasisManager.check returns restore when anomaly."""
    db = duckclaw.DuckClaw(":memory:")
    db.execute("CREATE SCHEMA IF NOT EXISTS test_worker2")
    db.execute("""
        CREATE TABLE IF NOT EXISTS test_worker2.agent_beliefs (
            belief_key VARCHAR PRIMARY KEY,
            target_value REAL NOT NULL,
            observed_value REAL,
            threshold REAL NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    config = {
        "beliefs": [{"key": "presupuesto", "target": 5000.0, "threshold": 500.0}],
        "actions": [{"trigger": "presupuesto_breach", "skill": "get_summary", "message": "Desviación."}],
    }
    from duckclaw.forge.homeostasis import HomeostasisManager

    reg = BeliefRegistry.from_config(config)
    mgr = HomeostasisManager(db=db, schema="test_worker2", registry=reg)
    plan = mgr.check("presupuesto", 3000.0, auto_update=True)
    assert plan["action"] == "restore"
    assert plan["skill_to_invoke"] == "get_summary"
    assert "Desviación" in plan["message"]


def test_homeostasis_manager_unknown_belief() -> None:
    """HomeostasisManager.check returns unknown for undefined belief."""
    db = duckclaw.DuckClaw(":memory:")
    db.execute("CREATE SCHEMA IF NOT EXISTS test_worker3")
    db.execute("""
        CREATE TABLE IF NOT EXISTS test_worker3.agent_beliefs (
            belief_key VARCHAR PRIMARY KEY,
            target_value REAL NOT NULL,
            observed_value REAL,
            threshold REAL NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    from duckclaw.forge.homeostasis import HomeostasisManager

    reg = BeliefRegistry.from_config({"beliefs": [], "actions": []})
    mgr = HomeostasisManager(db=db, schema="test_worker3", registry=reg)
    plan = mgr.check("unknown_key", 1.0, auto_update=False)
    assert plan["action"] == "unknown"
    assert "no definida" in plan["message"]


def test_register_homeostasis_skill_no_config() -> None:
    """register_homeostasis_skill does nothing when spec has no homeostasis_config."""
    from duckclaw.forge.skills.homeostasis_bridge import register_homeostasis_skill

    tools = []
    spec = type("Spec", (), {"homeostasis_config": None, "schema_name": "test"})()
    db = duckclaw.DuckClaw(":memory:")
    register_homeostasis_skill(tools, spec, db)
    assert len(tools) == 0


def test_register_homeostasis_skill_with_config() -> None:
    """register_homeostasis_skill adds homeostasis_check tool when config present."""
    from duckclaw.forge.skills.homeostasis_bridge import register_homeostasis_skill

    db = duckclaw.DuckClaw(":memory:")
    db.execute("CREATE SCHEMA IF NOT EXISTS finance_worker")
    db.execute("""
        CREATE TABLE IF NOT EXISTS finance_worker.agent_beliefs (
            belief_key VARCHAR PRIMARY KEY,
            target_value REAL NOT NULL,
            observed_value REAL,
            threshold REAL NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    spec = type("Spec", (), {
        "homeostasis_config": {
            "beliefs": [{"key": "presupuesto", "target": 5000.0, "threshold": 500.0}],
            "actions": [],
        },
        "schema_name": "finance_worker",
    })()
    tools = []
    register_homeostasis_skill(tools, spec, db)
    assert len(tools) == 1
    assert tools[0].name == "homeostasis_check"
    result = tools[0].invoke({"belief_key": "presupuesto", "observed_value": 4800.0})
    plan = json.loads(result)
    assert plan["action"] == "maintain"


def test_loader_ensures_agent_beliefs() -> None:
    """run_schema creates agent_beliefs table in worker schema."""
    from duckclaw.workers.loader import run_schema
    from duckclaw.workers.manifest import WorkerSpec
    from pathlib import Path

    db = duckclaw.DuckClaw(":memory:")
    spec = WorkerSpec(
        worker_id="test",
        name="Test",
        schema_name="test_schema",
        llm_required=None,
        temperature=0.2,
        topology="general",
        skills_list=[],
        allowed_tables=[],
        read_only=False,
        worker_dir=Path("."),
        homeostasis_config=None,
    )
    run_schema(db, spec)
    r = db.query("SELECT * FROM test_schema.agent_beliefs LIMIT 1")
    rows = json.loads(r) if isinstance(r, str) else (r or [])
    assert rows is not None

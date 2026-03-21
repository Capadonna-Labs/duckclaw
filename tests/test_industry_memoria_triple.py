"""Tests: plantilla industry (loader) y UnifiedMemoryOrchestrator (humo)."""

from __future__ import annotations

import json
def test_apply_industry_business_standard_creates_schemas(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import duckdb

    from duckclaw.forge.industries.loader import apply_industry_to_db

    con = duckdb.connect(":memory:")
    home = str(tmp_path).replace("'", "''")
    con.execute(f"SET home_directory='{home}';")
    apply_industry_to_db(con, "business_standard")
    n = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema IN ('core','rbac','org','flow')"
    ).fetchone()[0]
    assert int(n) >= 6
    con.close()


def test_seed_industry_agent_config_inserts_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import duckdb

    from duckclaw.forge.industries.loader import seed_industry_agent_config

    con = duckdb.connect(":memory:")
    seed_industry_agent_config(con, "business_standard")
    row = con.execute(
        "SELECT value FROM main.agent_config WHERE key = 'industry_template'"
    ).fetchone()
    assert row and row[0] == "business_standard"
    con.close()


def test_classify_memory_route_prefers_sql_for_conteo():
    from duckclaw.forge.skills.unified_memory_orchestrator import classify_memory_route

    r = classify_memory_route("¿Cuántos roles hay en el sistema?")
    assert "sql" in r


def test_run_unified_memory_returns_valid_json():
    from duckclaw.forge.skills.unified_memory_orchestrator import run_unified_memory

    class _Dummy:
        def execute(self, *_a, **_k):
            return None

        def query(self, sql: str, *_a, **_k):
            _ = sql
            return "[]"

    out = run_unified_memory(_Dummy(), "conteo de roles")
    data = json.loads(out)
    assert set(data.keys()) == {"sql_data", "graph_relations", "semantic_matches"}
    assert isinstance(data["sql_data"], list)


def test_ensure_tenant_industry_db_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from duckclaw.vaults import ensure_tenant_industry_db

    p = ensure_tenant_industry_db("acme_corp")
    assert p.name == "default.duckdb"
    assert "private" in str(p).replace("\\", "/")
    assert p.is_file()

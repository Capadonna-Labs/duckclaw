"""Unit tests for bicameral memory architecture (DuckDB native + PGQ)."""

from __future__ import annotations

from pathlib import Path

import duckclaw
from duckclaw.agents import (
    BicameralOrchestrator,
    DataMasker,
    DuckDBNativeEngine,
    SQLValidator,
    normalize_db_path,
)


def test_normalize_db_path() -> None:
    assert normalize_db_path("", "duckclaw.db") == "db/duckclaw.db"
    assert normalize_db_path("telegram.duckdb", "duckclaw.db") == "db/telegram.duckdb"
    assert normalize_db_path("db/test.duckdb", "duckclaw.db") == "db/test.duckdb"
    assert normalize_db_path(":memory:", "duckclaw.db") == ":memory:"


def test_sql_validator_read_and_pgq() -> None:
    validator = SQLValidator()
    ok, _ = validator.validate_read_sql("SELECT 1")
    assert ok
    ok, _ = validator.validate_pgq_sql(
        "SELECT * FROM GRAPH_TABLE(financial_graph MATCH (a)-[r]->(b) COLUMNS (a.id,b.id))"
    )
    assert ok
    ok, err = validator.validate_read_sql("DROP TABLE x")
    assert not ok
    assert "bloqueada" in err


def test_data_masker() -> None:
    masker = DataMasker()
    payload = '[{"source":"user_1","target":"acct_2","amount":1200}]'
    masked = masker.mask_rows(payload)
    assert '"source": "***"' in masked
    assert '"target": "***"' in masked


def test_duckdb_native_engine_fallback_search(tmp_path: Path) -> None:
    db_path = tmp_path / "db" / "duckclaw.db"
    engine = DuckDBNativeEngine(db_path=str(db_path))
    engine.upsert_relations(
        [
            {"source": "user_123", "target": "store_abc", "relation": "RELATED_TO", "amount": 2500},
            {"source": "user_123", "target": "bank_xyz", "relation": "RELATED_TO", "amount": 1000},
        ]
    )
    out = engine.search_relations("user_123", limit=5)
    assert out["source_id"] in ("duckdb_pgq", "duckdb_graph_fallback")
    assert "result" in out
    assert db_path.exists()


def test_bicameral_orchestrator_run_and_trace(tmp_path: Path) -> None:
    db = duckclaw.DuckClaw(":memory:")
    db.execute(
        "CREATE TABLE IF NOT EXISTS transfers (id TEXT, from_account TEXT, to_account TEXT, amount DOUBLE, relation TEXT)"
    )
    db.execute(
        "INSERT INTO transfers VALUES ('t1','user_1','store_1',1200,'RELATED_TO'),('t2','user_1','bank_1',500,'RELATED_TO')"
    )
    engine = DuckDBNativeEngine(db=db, db_path=":memory:")
    trace_path = tmp_path / "db" / "bicameral_traces.jsonl"
    orchestrator = BicameralOrchestrator(engine=engine, trace_path=str(trace_path))
    ctx = orchestrator.run_query("cual es el total y su relacion con user_1")
    assert "Bicameral Context" in ctx.prompt
    assert "source_ids" in ctx.prompt
    assert trace_path.exists()
    assert trace_path.read_text(encoding="utf-8").strip()


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    test_normalize_db_path()
    test_sql_validator_read_and_pgq()
    test_data_masker()
    with TemporaryDirectory() as d1:
        test_duckdb_native_engine_fallback_search(Path(d1))
    with TemporaryDirectory() as d2:
        test_bicameral_orchestrator_run_and_trace(Path(d2))
    print("All tests passed.")

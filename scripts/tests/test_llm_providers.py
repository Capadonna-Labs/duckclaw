"""Tests for DuckClaw LLM integration: guardrails and tools (safe_write)."""

import duckclaw
from duckclaw.integrations.llm_providers import (
    build_agent_graph,
    build_duckclaw_tools,
    _validate_read_sql,
    _validate_write_sql,
    _safe_table_name,
)


def test_safe_table_name() -> None:
    assert _safe_table_name("telegram_messages") == "telegram_messages"
    assert _safe_table_name("t1") == "t1"
    assert _safe_table_name("") is None
    assert _safe_table_name("a; DROP TABLE x") is None
    assert _safe_table_name("a-b") is None


def test_validate_read_sql() -> None:
    ok, _ = _validate_read_sql("SELECT * FROM t")
    assert ok
    ok, _ = _validate_read_sql("WITH cte AS (SELECT 1) SELECT * FROM cte")
    assert ok
    ok, _ = _validate_read_sql("SHOW TABLES")
    assert ok
    ok, err = _validate_read_sql("DROP TABLE t")
    assert not ok
    assert "DROP" in err or "permiten" in err
    ok, err = _validate_read_sql("INSERT INTO t VALUES (1)")
    assert not ok
    ok, err = _validate_read_sql("")
    assert not ok


def test_validate_write_sql() -> None:
    ok, _ = _validate_write_sql("INSERT INTO t (a) VALUES (1)")
    assert ok
    ok, _ = _validate_write_sql("UPDATE t SET a = 1")
    assert ok
    ok, _ = _validate_write_sql("DELETE FROM t")
    assert ok
    ok, err = _validate_write_sql("DROP TABLE t")
    assert not ok
    assert "DROP" in err or "No se permiten" in err
    ok, err = _validate_write_sql("SELECT * FROM t")
    assert not ok
    ok, err = _validate_write_sql("CREATE TABLE x (id INT)")
    assert not ok


def test_tools_list_describe_read_write() -> None:
    db = duckclaw.DuckClaw(":memory:")
    db.execute("CREATE TABLE test (id INTEGER, name TEXT)")
    db.execute("INSERT INTO test VALUES (1, 'a'), (2, 'b')")
    tools = build_duckclaw_tools(db)
    by_name = {t.name: t for t in tools}
    assert "list_tables" in by_name
    assert "describe_table" in by_name
    assert "run_read_sql" in by_name
    assert "run_write_sql" in by_name

    out = by_name["list_tables"].invoke({})
    assert "test" in out

    out = by_name["describe_table"].invoke({"table_name": "test"})
    assert "id" in out and "name" in out

    out = by_name["run_read_sql"].invoke({"sql": "SELECT * FROM test"})
    assert "1" in out and "a" in out

    out = by_name["run_write_sql"].invoke({"sql": "INSERT INTO test VALUES (3, 'c')"})
    assert out == "OK"
    out = by_name["run_read_sql"].invoke({"sql": "SELECT COUNT(*) FROM test"})
    assert "3" in out


def test_tools_block_ddl() -> None:
    db = duckclaw.DuckClaw(":memory:")
    db.execute("CREATE TABLE t (id INT)")
    tools = build_duckclaw_tools(db)
    run_write = next(t for t in tools if t.name == "run_write_sql")
    run_read = next(t for t in tools if t.name == "run_read_sql")

    out = run_write.invoke({"sql": "DROP TABLE t"})
    assert "OK" not in out
    assert "No se permiten" in out or "DROP" in out

    out = run_read.invoke({"sql": "DROP TABLE t"})
    assert "Error" in out or "permiten" in out


def test_build_agent_graph_none_llm() -> None:
    db = duckclaw.DuckClaw(":memory:")
    db.execute(
        "CREATE TABLE telegram_messages (message_id BIGINT, chat_id BIGINT, user_id BIGINT, "
        "username TEXT, text TEXT, raw_update_json TEXT, received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    graph = build_agent_graph(db, llm=None)
    result = graph.invoke({"incoming": "hola"})
    assert "reply" in result
    assert "hola" in result["reply"] or "Recibí" in result["reply"]


if __name__ == "__main__":
    test_safe_table_name()
    test_validate_read_sql()
    test_validate_write_sql()
    test_tools_list_describe_read_write()
    test_tools_block_ddl()
    test_build_agent_graph_none_llm()
    print("All tests passed.")

"""Tests for duckclaw.utils.sql_safe."""

from duckclaw.utils.sql_safe import (
    escape_like,
    escape_value,
    is_safe_identifier,
    safe_identifier,
    validate_read_sql,
)
import pytest


class TestSafeIdentifier:
    def test_valid_identifiers(self) -> None:
        assert safe_identifier("users") == "users"
        assert safe_identifier("my_table") == "my_table"
        assert safe_identifier("_private") == "_private"
        assert safe_identifier("T1") == "T1"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            safe_identifier("")
        with pytest.raises(ValueError):
            safe_identifier("a; DROP TABLE x")
        with pytest.raises(ValueError):
            safe_identifier("a-b")
        with pytest.raises(ValueError):
            safe_identifier("123start")
        with pytest.raises(ValueError):
            safe_identifier("table name")

    def test_is_safe_identifier(self) -> None:
        assert is_safe_identifier("ok_name")
        assert not is_safe_identifier("")
        assert not is_safe_identifier("no spaces")
        assert not is_safe_identifier("no;inject")


class TestEscapeValue:
    def test_quotes_doubled(self) -> None:
        assert escape_value("it's") == "it''s"
        assert escape_value("a''b") == "a''''b"

    def test_max_len(self) -> None:
        assert escape_value("abcdef", max_len=3) == "abc"

    def test_empty(self) -> None:
        assert escape_value("") == ""

    def test_no_truncation_when_zero(self) -> None:
        long_str = "x" * 1000
        assert len(escape_value(long_str)) == 1000


class TestEscapeLike:
    def test_percent_escaped(self) -> None:
        assert "\\%" in escape_like("100%")

    def test_underscore_escaped(self) -> None:
        assert "\\_" in escape_like("a_b")

    def test_quotes_escaped(self) -> None:
        assert "''" in escape_like("it's")

    def test_plain_value(self) -> None:
        assert escape_like("hello") == "hello"


class TestValidateReadSql:
    def test_select_ok(self) -> None:
        ok, _ = validate_read_sql("SELECT * FROM t")
        assert ok

    def test_with_ok(self) -> None:
        ok, _ = validate_read_sql("WITH cte AS (SELECT 1) SELECT * FROM cte")
        assert ok

    def test_show_ok(self) -> None:
        ok, _ = validate_read_sql("SHOW TABLES")
        assert ok

    def test_empty_rejected(self) -> None:
        ok, err = validate_read_sql("")
        assert not ok
        assert "vacío" in err

    def test_drop_rejected(self) -> None:
        ok, err = validate_read_sql("DROP TABLE t")
        assert not ok
        assert "SELECT" in err or "DROP" in err

    def test_insert_rejected(self) -> None:
        ok, err = validate_read_sql("SELECT 1; INSERT INTO t VALUES (1)")
        assert not ok

    def test_update_rejected(self) -> None:
        ok, _ = validate_read_sql("UPDATE t SET x = 1")
        assert not ok

    def test_delete_rejected(self) -> None:
        ok, _ = validate_read_sql("DELETE FROM t")
        assert not ok

    def test_create_in_select_rejected(self) -> None:
        ok, _ = validate_read_sql("SELECT * FROM t WHERE CREATE = 1")
        assert not ok

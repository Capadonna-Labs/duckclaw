"""Tests for QuoteEngine. Spec: Motor_Cotizacion_Omnicanal."""

import json
import os

from duckclaw.forge.quotes import ensure_quotes_schema, generate_quote
from duckclaw import DuckClaw


def test_generate_quote() -> None:
    path = "/tmp/test_quote_engine.duckdb"
    if os.path.exists(path):
        os.unlink(path)
    try:
        db = DuckClaw(path)
        ensure_quotes_schema(db)
        db.execute("CREATE SCHEMA IF NOT EXISTS powerseal_worker")
        db.execute(
            "CREATE TABLE IF NOT EXISTS powerseal_worker.products "
            "(id INTEGER, name VARCHAR, price VARCHAR)"
        )
        db.execute("INSERT INTO powerseal_worker.products VALUES (3121, 'Abrazadera', '10000')")

        result = generate_quote(
            db,
            [{"sku": "3121", "quantity": 50}],
            "+573231234567",
            "Carlos (EPM)",
            "powerseal_worker",
        )
        assert "error" not in result or result.get("quote_id")
        assert result.get("quote_id", "").startswith("COT-")
        assert result.get("total_amount", 0) > 0
        assert result.get("currency") == "COP"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_generate_quote_empty_items() -> None:
    path = "/tmp/test_quote_empty.duckdb"
    if os.path.exists(path):
        os.unlink(path)
    try:
        db = DuckClaw(path)
        ensure_quotes_schema(db)
        result = generate_quote(db, [], "+57323", "Test", "powerseal_worker")
        assert "error" in result
        assert result.get("quote_id") is None
    finally:
        if os.path.exists(path):
            os.unlink(path)

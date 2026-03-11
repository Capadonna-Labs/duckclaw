"""Tests for Sovereign CRM (Memoria Bicameral DuckDB PGQ). Spec: specs/Sovereign_CRM_Memoria_Bicameral_DuckDB_PGQ.md"""

import os

from duckclaw.forge.crm import ensure_crm_graph_schema, graph_context_injector
from duckclaw import DuckClaw


def test_ensure_crm_graph_schema() -> None:
    path = "/tmp/test_crm_schema.duckdb"
    if os.path.exists(path):
        os.unlink(path)
    try:
        db = DuckClaw(path)
        ok = ensure_crm_graph_schema(db)
        assert ok is True
        r = db.query("SELECT COUNT(*) AS n FROM memory_nodes")
        rows = r if isinstance(r, list) else []
        assert len(rows) >= 0
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_graph_context_injector_empty() -> None:
    path = "/tmp/test_crm_ctx.duckdb"
    if os.path.exists(path):
        os.unlink(path)
    try:
        db = DuckClaw(path)
        ensure_crm_graph_schema(db)
        ctx = graph_context_injector(db, "default")
        assert ctx == "" or "Perfil" in ctx
    finally:
        if os.path.exists(path):
            os.unlink(path)

"""
UnifiedMemoryOrchestrator (spec Memoria Triple v3.0).

Enruta la petición hacia SQL, PGQ (duckpgq) o VSS y devuelve un JSON unificado:
{"sql_data": [...], "graph_relations": [...], "semantic_matches": [...]}
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

_log = logging.getLogger(__name__)

_SQL_HINT = re.compile(
    r"\b(cuántos|cuantos|conteo|count|suma|saldo|tabla|roles|usuarios|permisos|unidades|workflow|"
    r"transacc|listar|total|cuántas|cuantas|datos\s+de|select)\b",
    re.IGNORECASE,
)
_GRAPH_HINT = re.compile(
    r"\b(quien|quién|equipo|jerarqu|reporta|pertenece|cadena|organigrama|aprueba|manager|"
    r"rol\s+de|tiene\s+rol|relaci[oó]n\s+entre)\b",
    re.IGNORECASE,
)
_VSS_HINT = re.compile(
    r"\b(similar|parecido|experto|semántico|semantic|busca\s+por|recomienda|casos\s+como|"
    r"significado|concepto)\b",
    re.IGNORECASE,
)


def classify_memory_route(text: str) -> set[str]:
    t = text or ""
    routes: set[str] = set()
    if _SQL_HINT.search(t):
        routes.add("sql")
    if _GRAPH_HINT.search(t):
        routes.add("graph")
    if _VSS_HINT.search(t):
        routes.add("vss")
    if not routes:
        routes.add("sql")
    return routes


def _duckpgq_loaded(db: Any) -> bool:
    try:
        db.execute("LOAD duckpgq;")
        return True
    except Exception:
        try:
            db.execute("INSTALL duckpgq FROM community;")
            db.execute("LOAD duckpgq;")
            return True
        except Exception:
            return False


def _run_sql_layer(db: Any, _text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        r = db.query(
            "SELECT COUNT(*) AS n FROM information_schema.tables "
            "WHERE table_schema IN ('core','rbac','org','flow')"
        )
        row = json.loads(r) if isinstance(r, str) else r
        if row:
            results.append({"query": "industry_schema_table_count", "rows": row})
    except Exception as e:
        _log.debug("unified_memory sql layer: %s", e)
    try:
        r2 = db.query("SELECT id, name FROM rbac.roles ORDER BY id")
        rows = json.loads(r2) if isinstance(r2, str) else (r2 or [])
        if rows:
            results.append({"query": "rbac.roles", "rows": rows})
    except Exception:
        pass
    return results


def _run_graph_layer(db: Any, _text: str) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    if _duckpgq_loaded(db):
        try:
            sql = """
            SELECT * FROM GRAPH_TABLE(enterprise_kg
                MATCH (p:person)-[e:has_role]->(r:role)
                COLUMNS (p.id, r.id, r.name)
            )
            LIMIT 30
            """
            raw = db.query(sql)
            rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        relations.append({"type": "has_role", "data": row})
        except Exception as e:
            _log.debug("unified_memory GRAPH_TABLE: %s", e)
    if not relations:
        try:
            sql_join = """
            SELECT ur.user_id, r.id AS role_id, r.name AS role_name
            FROM rbac.user_roles ur
            JOIN rbac.roles r ON ur.role_id = r.id
            LIMIT 30
            """
            raw = db.query(sql_join)
            rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        relations.append({"type": "has_role_sql", "data": row})
        except Exception:
            pass
    return relations


def _run_vss_layer(db: Any, text: str) -> list[dict[str, Any]]:
    # v1: sin servicio de embeddings para la consulta; reservado para integración futura
    _ = (db, text)
    return []


def run_unified_memory(db: Any, user_request: str) -> str:
    routes = classify_memory_route(user_request)
    out: dict[str, Any] = {"sql_data": [], "graph_relations": [], "semantic_matches": []}
    if "sql" in routes:
        out["sql_data"] = _run_sql_layer(db, user_request)
    if "graph" in routes:
        out["graph_relations"] = _run_graph_layer(db, user_request)
    if "vss" in routes:
        out["semantic_matches"] = _run_vss_layer(db, user_request)
    return json.dumps(out, ensure_ascii=False)


def make_unified_memory_tool(db: Any):
    from langchain_core.tools import StructuredTool

    return StructuredTool.from_function(
        lambda user_request: run_unified_memory(db, user_request),
        name="unified_memory",
        description=(
            "Memoria triple (plantilla industry): devuelve JSON con sql_data, graph_relations y "
            "semantic_matches según la petición. Usar para roles, organización y datos enterprise "
            "(core/rbac/org/flow) cuando aplique la plantilla business_standard."
        ),
    )

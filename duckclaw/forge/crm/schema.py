"""
Schema CRM: memory_nodes, memory_edges, property graph powerseal_crm.

Spec: specs/Sovereign_CRM_Memoria_Bicameral_DuckDB_PGQ.md
"""

from __future__ import annotations

from typing import Any

# Ontología B2B Power Seal
CRM_NODE_LABELS = frozenset({"Lead", "Company", "Product"})
CRM_RELATIONSHIPS = frozenset({"WORKS_AT", "INTERESTED_IN", "PURCHASED"})

_CRM_GRAPH_AVAILABLE: bool | None = None


def _crm_pgq_available(db: Any) -> bool:
    global _CRM_GRAPH_AVAILABLE
    if _CRM_GRAPH_AVAILABLE is not None:
        return _CRM_GRAPH_AVAILABLE
    try:
        db.execute("INSTALL duckpgq FROM community;")
        db.execute("LOAD duckpgq;")
        _CRM_GRAPH_AVAILABLE = True
    except Exception:
        _CRM_GRAPH_AVAILABLE = False
    return _CRM_GRAPH_AVAILABLE


def ensure_crm_graph_schema(db: Any) -> bool:
    """
    Crea/actualiza memory_nodes, memory_edges (con properties opcional) y property graph powerseal_crm.
    Retorna True si PGQ está disponible.
    """
    db.execute("""
        CREATE TABLE IF NOT EXISTS memory_nodes (
            node_id VARCHAR PRIMARY KEY,
            label VARCHAR,
            properties JSON
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS memory_edges (
            edge_id VARCHAR PRIMARY KEY,
            source_id VARCHAR,
            target_id VARCHAR,
            relationship VARCHAR,
            weight DOUBLE DEFAULT 1.0,
            properties JSON,
            FOREIGN KEY (source_id) REFERENCES memory_nodes(node_id),
            FOREIGN KEY (target_id) REFERENCES memory_nodes(node_id)
        )
    """)
    # Migración: añadir properties a memory_edges si no existe
    try:
        r = db.query(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='memory_edges' AND column_name='properties' LIMIT 1"
        )
        rows = r if isinstance(r, list) else ([] if not r else [r])
        if not rows:
            db.execute("ALTER TABLE memory_edges ADD COLUMN properties JSON")
    except Exception:
        pass

    if not _crm_pgq_available(db):
        return False
    try:
        db.execute("DROP PROPERTY GRAPH IF EXISTS powerseal_crm")
        db.execute("""
            CREATE PROPERTY GRAPH powerseal_crm
            VERTEX TABLES (memory_nodes LABEL entity)
            EDGE TABLES (
                memory_edges SOURCE KEY (source_id) REFERENCES memory_nodes (node_id)
                             DESTINATION KEY (target_id) REFERENCES memory_nodes (node_id)
                             LABEL relation
            )
        """)
    except Exception:
        return False
    return True

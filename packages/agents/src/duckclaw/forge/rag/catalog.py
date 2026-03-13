"""Esquema y búsqueda semántica en catalog_items (DuckDB VSS)."""

from __future__ import annotations

import json
from typing import Any, List, Optional

_VSS_AVAILABLE: Optional[bool] = None


def _vss_available(db: Any) -> bool:
    global _VSS_AVAILABLE
    if _VSS_AVAILABLE is not None:
        return _VSS_AVAILABLE
    try:
        db.execute("INSTALL vss")
        db.execute("LOAD vss")
        _VSS_AVAILABLE = True
    except Exception:
        _VSS_AVAILABLE = False
    return _VSS_AVAILABLE


def ensure_catalog_schema(db: Any, schema: str) -> bool:
    """
    Crea catalog_items con columna embedding. Si vss está disponible, crea índice HNSW.
    Retorna True si el esquema vectorial está listo.
    """
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in schema.strip())
    try:
        db.execute(f"CREATE SCHEMA IF NOT EXISTS {safe}")
        # Tabla con embedding 384 (all-MiniLM) o 768 (nomic); embedding nullable
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS {safe}.catalog_items (
                sku VARCHAR PRIMARY KEY,
                name VARCHAR,
                description TEXT,
                price DECIMAL,
                stock_status VARCHAR,
                embedding FLOAT[384]
            )
        """)
        if _vss_available(db):
            try:
                db.execute(
                    f"CREATE INDEX IF NOT EXISTS catalog_hnsw_idx ON {safe}.catalog_items "
                    "USING HNSW (embedding) WITH (metric = 'cosine')"
                )
            except Exception:
                pass
        return True
    except Exception:
        return False


def search_catalog_semantic(
    db: Any,
    schema: str,
    query_embedding: List[float],
    limit: int = 5,
    max_distance: float = 0.3,
) -> List[dict]:
    """
    Búsqueda por similitud coseno. Retorna productos con distance < max_distance.
    """
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in schema.strip())
    vec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    try:
        r = db.query(
            f"""
            SELECT sku, name, description, price, stock_status,
                   array_cosine_distance(embedding, {vec_str}::FLOAT[384]) AS dist
            FROM {safe}.catalog_items
            WHERE embedding IS NOT NULL
            ORDER BY dist ASC
            LIMIT {max(1, min(limit, 20))}
            """
        )
        rows = json.loads(r) if isinstance(r, str) else (r or [])
        return [row for row in rows if isinstance(row, dict) and row.get("dist", 2) < max_distance]
    except Exception:
        return []

"""Skill: search_products — busca productos en el catálogo (DB o cache)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool


def get_tools(db: Any, schema_name: str, spec: Any = None) -> list:
    schema = schema_name

    def search_products(query: str, limit: int = 10) -> str:
        """
        Busca productos en el catálogo por nombre, categoría o descripción.
        Si la tabla products está vacía, sugiere usar fetch_product_catalog primero.
        """
        try:
            esc = str(query).replace("'", "''")[:300]
            r = db.query(
                f"SELECT id, name, description, category, price, stock_status FROM {schema}.products "
                f"WHERE name LIKE '%' || '{esc}' || '%' OR description LIKE '%' || '{esc}' || '%' OR category LIKE '%' || '{esc}' || '%' "
                f"ORDER BY id LIMIT {max(1, min(limit, 20))}"
            )
            rows = json.loads(r) if isinstance(r, str) else (r or [])
            if not rows:
                return json.dumps({
                    "message": "No hay productos en cache. Usa fetch_product_catalog para obtener el catálogo desde la web.",
                    "results": [],
                })
            return json.dumps({"results": rows})
        except Exception as e:
            return json.dumps({"error": str(e), "results": []})

    return [
        StructuredTool.from_function(
            search_products,
            name="search_products",
            description="Busca productos por nombre, categoría o descripción. query: texto; limit: máx resultados (default 10).",
        )
    ]

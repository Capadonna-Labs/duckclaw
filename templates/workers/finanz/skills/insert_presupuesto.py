"""Skill: insert_presupuesto — registra un presupuesto por categoría y mes."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool


def get_tools(db: Any, schema_name: str, spec: Any = None) -> list:
    schema = schema_name

    def insert_presupuesto(category_id: int, amount: float, year: int = 0, month: int = 0) -> str:
        """Registra o actualiza presupuesto mensual por categoría. category_id: id de categoría; amount: monto presupuestado; year: año (default actual); month: mes 1-12 (default actual)."""
        try:
            from datetime import datetime
            now = datetime.now()
            y = year if year else now.year
            m = month if month else now.month
            if m < 1 or m > 12:
                return json.dumps({"error": "month debe ser 1-12"})
            r = db.query(
                f"SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM {schema}.presupuestos"
            )
            rows = json.loads(r) if isinstance(r, str) else (r or [])
            next_id = int(rows[0].get("next_id", 1)) if rows else 1
            db.execute(
                f"INSERT INTO {schema}.presupuestos (id, category_id, amount, year, month) "
                f"VALUES ({next_id}, {int(category_id)}, {float(amount)}, {y}, {m}) "
                f"ON CONFLICT (category_id, year, month) DO UPDATE SET amount = EXCLUDED.amount"
            )
            return json.dumps({"status": "ok", "message": f"Presupuesto ${amount:,.0f} para categoría {category_id} ({y}-{m:02d})."})
        except Exception as e:
            return json.dumps({"error": str(e)})

    return [
        StructuredTool.from_function(
            insert_presupuesto,
            name="insert_presupuesto",
            description="Registra o actualiza presupuesto mensual por categoría. category_id (id de categoría), amount (monto presupuestado), year (opcional), month (1-12, opcional). Sin year/month usa el mes actual.",
        )
    ]

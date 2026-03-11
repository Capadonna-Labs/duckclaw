"""Skill: get_presupuesto_vs_real — compara presupuesto vs gasto real por categoría."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool


def get_tools(db: Any, schema_name: str, spec: Any = None) -> list:
    schema = schema_name

    def get_presupuesto_vs_real(year: int = 0, month: int = 0) -> str:
        """Compara presupuesto vs gasto real por categoría. year y month opcionales (default: mes actual)."""
        try:
            from datetime import datetime
            now = datetime.now()
            y = year if year else now.year
            m = month if month else now.month
            if m < 1 or m > 12:
                return json.dumps({"error": "month debe ser 1-12"})
            r = db.query(
                f"""
                SELECT c.name AS categoria, COALESCE(p.amount, 0) AS presupuestado,
                       COALESCE(SUM(CASE WHEN t.amount < 0 THEN ABS(t.amount) ELSE 0 END), 0) AS gastado,
                       COALESCE(p.amount, 0) - COALESCE(SUM(CASE WHEN t.amount < 0 THEN ABS(t.amount) ELSE 0 END), 0) AS diferencia
                FROM {schema}.categories c
                LEFT JOIN {schema}.presupuestos p ON p.category_id = c.id AND p.year = {y} AND p.month = {m}
                LEFT JOIN {schema}.transactions t ON t.category_id = c.id
                  AND strftime('%Y', t.tx_date) = '{y}' AND strftime('%m', t.tx_date) = '{m:02d}'
                GROUP BY c.id, c.name, p.amount
                ORDER BY c.name
                """
            )
            return r
        except Exception as e:
            return json.dumps({"error": str(e)})

    return [
        StructuredTool.from_function(
            get_presupuesto_vs_real,
            name="get_presupuesto_vs_real",
            description="Compara presupuesto vs gasto real por categoría. year y month opcionales (default: mes actual). Muestra presupuestado, gastado y diferencia.",
        )
    ]

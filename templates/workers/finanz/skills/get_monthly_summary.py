"""Skill: get_monthly_summary — resumen mensual de transacciones."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool


def get_tools(db: Any, schema_name: str, spec: Any = None) -> list:
    schema = schema_name

    def get_monthly_summary(year: int = 0, month: int = 0) -> str:
        """Devuelve resumen mensual: total ingresos, total gastos, balance. year y month opcionales (default: mes actual)."""
        try:
            if year and month:
                r = db.query(
                    f"SELECT SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS ingresos, "
                    f"SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END) AS gastos, "
                    f"SUM(amount) AS balance FROM {schema}.transactions "
                    f"WHERE strftime('%Y', tx_date) = '{year}' AND strftime('%m', tx_date) = '{month:02d}'"
                )
            else:
                r = db.query(
                    f"SELECT SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS ingresos, "
                    f"SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END) AS gastos, "
                    f"SUM(amount) AS balance FROM {schema}.transactions "
                    f"WHERE strftime('%Y-%m', tx_date) = strftime('%Y-%m', CURRENT_DATE)"
                )
            return r
        except Exception as e:
            return f'{{"error": "{e}"}}'

    return [
        StructuredTool.from_function(
            get_monthly_summary,
            name="get_monthly_summary",
            description="Resumen mensual: ingresos, gastos y balance. Parámetros opcionales: year (ej. 2025), month (1-12). Sin parámetros usa el mes actual.",
        )
    ]

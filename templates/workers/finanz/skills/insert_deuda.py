"""Skill: insert_deuda — registra una deuda en finance_worker.deudas."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool


def get_tools(db: Any, schema_name: str, spec: Any = None) -> list:
    schema = schema_name

    def insert_deuda(amount: float, description: str = "", creditor: str = "", due_date: str = "") -> str:
        """Registra una deuda. amount: monto; description: descripción; creditor: acreedor; due_date: fecha vencimiento (YYYY-MM-DD)."""
        try:
            desc_esc = str(description or "").replace("'", "''")[:500]
            cred_esc = str(creditor or "").replace("'", "''")[:200]
            date_val = f"DATE '{due_date}'" if due_date else "NULL"
            r = db.query(f"SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM {schema}.deudas")
            rows = json.loads(r) if isinstance(r, str) else (r or [])
            next_id = int(rows[0].get("next_id", 1)) if rows else 1
            db.execute(
                f"INSERT INTO {schema}.deudas (id, amount, description, creditor, due_date) "
                f"VALUES ({next_id}, {float(amount)}, '{desc_esc}', '{cred_esc}', {date_val})"
            )
            return json.dumps({"status": "ok", "message": "Deuda registrada."})
        except Exception as e:
            return json.dumps({"error": str(e)})

    return [
        StructuredTool.from_function(
            insert_deuda,
            name="insert_deuda",
            description="Registra una deuda. amount (monto), description (opcional), creditor (acreedor, opcional), due_date (YYYY-MM-DD, opcional).",
        )
    ]

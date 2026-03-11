"""Skill: insert_cuenta — registra una cuenta bancaria en finance_worker.cuentas."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool


def get_tools(db: Any, schema_name: str, spec: Any = None) -> list:
    schema = schema_name

    def insert_cuenta(name: str, balance: float = 0, currency: str = "COP") -> str:
        """Registra una cuenta bancaria. name: nombre; balance: saldo inicial (default 0); currency: moneda (default COP)."""
        try:
            esc = str(name or "").replace("'", "''")[:200]
            curr_esc = str(currency or "COP").replace("'", "''")[:10]
            r = db.query(f"SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM {schema}.cuentas")
            rows = json.loads(r) if isinstance(r, str) else (r or [])
            next_id = int(rows[0].get("next_id", 1)) if rows else 1
            db.execute(
                f"INSERT INTO {schema}.cuentas (id, name, balance, currency) "
                f"VALUES ({next_id}, '{esc}', {float(balance)}, '{curr_esc}')"
            )
            return json.dumps({"status": "ok", "message": "Cuenta registrada."})
        except Exception as e:
            return json.dumps({"error": str(e)})

    return [
        StructuredTool.from_function(
            insert_cuenta,
            name="insert_cuenta",
            description="Registra una cuenta bancaria. name (nombre de la cuenta), balance (saldo inicial, default 0), currency (default COP).",
        )
    ]

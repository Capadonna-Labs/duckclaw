"""
DDL MVP Leila: ejecuta el schema.sql de la plantilla LeilaAssistant (main.*).

Spec: specs/features/Asistente de Leila — MVP Telegram.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from duckclaw.workers.loader import _split_sql

_SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "templates" / "LeilaAssistant" / "schema.sql"


def ensure_leila_mvp_schema(db: Any) -> None:
    """Crea leila_products y leila_orders si no existen (definición en forge/templates/LeilaAssistant/schema.sql)."""
    sql = _SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    for stmt in _split_sql(sql):
        if stmt.strip():
            db.execute(stmt)

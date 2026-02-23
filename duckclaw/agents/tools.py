"""Herramientas genéricas que usan el motor C++ DuckClaw."""

from __future__ import annotations

import json
import re
from typing import Any

# Solo lectura para run_sql cuando no es escritura
_READ_ONLY = re.compile(r"^\s*(SELECT|WITH|SHOW|DESCRIBE)\s", re.IGNORECASE)
_BLOCKED = re.compile(
    r"\b(DROP|ALTER|TRUNCATE|CREATE|ATTACH|DETACH|COPY|EXPORT|IMPORT)\b",
    re.IGNORECASE,
)

_MEMORY_TABLE = "agent_memory"


def _ensure_memory_table(db: Any) -> None:
    db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MEMORY_TABLE} (
            key VARCHAR PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def run_sql(db: Any, query: str) -> str:
    """Ejecuta SQL y retorna JSON. Para SELECT/WITH/SHOW/DESCRIBE devuelve filas; para escritura devuelve {\"status\":\"ok\"}."""
    if not query or not query.strip():
        return json.dumps({"error": "Query vacío."})
    q = query.strip()
    if _BLOCKED.search(q):
        return json.dumps({"error": "Comando no permitido (DROP, ALTER, etc.)."})
    try:
        if _READ_ONLY.search(q):
            return db.query(q)
        db.execute(q)
        return json.dumps({"status": "ok"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def inspect_schema(db: Any) -> str:
    """Retorna la estructura de la DB actual: tablas y columnas en JSON."""
    try:
        tables = json.loads(
            db.query(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            )
        )
        out = []
        for t in tables if isinstance(tables, list) else []:
            name = t.get("table_name") if isinstance(t, dict) else None
            if not name:
                continue
            name_esc = str(name).replace("'", "''")
            cols = db.query(
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_schema = 'main' AND table_name = '{name_esc}' ORDER BY ordinal_position"
            )
            out.append({"table": name, "columns": json.loads(cols)})
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def manage_memory(db: Any, action: str, key: str, value: str = "") -> str:
    """Gestiona preferencias del usuario. action: 'get' | 'set' | 'delete'. key: clave. value: solo para 'set'."""
    _ensure_memory_table(db)
    key_safe = str(key).replace("'", "''")[:512]
    value_safe = str(value).replace("'", "''")[:4096]
    try:
        if action == "get":
            r = db.query(
                f"SELECT value FROM {_MEMORY_TABLE} WHERE key = '{key_safe}' LIMIT 1"
            )
            data = json.loads(r)
            if data and isinstance(data, list) and len(data) > 0:
                return json.dumps({"value": (data[0].get("value") if isinstance(data[0], dict) else None)})
            return json.dumps({"value": None})
        if action == "set":
            db.execute(
                f"""
                INSERT INTO {_MEMORY_TABLE} (key, value) VALUES ('{key_safe}', '{value_safe}')
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                """
            )
            return json.dumps({"status": "ok"})
        if action == "delete":
            db.execute(f"DELETE FROM {_MEMORY_TABLE} WHERE key = '{key_safe}'")
            return json.dumps({"status": "ok"})
        return json.dumps({"error": f"action debe ser get, set o delete"})
    except Exception as e:
        return json.dumps({"error": str(e)})

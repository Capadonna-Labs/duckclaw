"""Herramientas genéricas que usan el motor C++ DuckClaw."""

from __future__ import annotations

import json
from typing import Any

_MEMORY_TABLE = "agent_memory"

# SQLValidator for run_sql (SecurityGateway)
_sql_validator: Any = None


def _get_sql_validator() -> Any:
    """Lazy init SQLValidator for run_sql."""
    global _sql_validator
    if _sql_validator is None:
        try:
            from duckclaw.security import SQLValidator

            _sql_validator = SQLValidator(read_only=False)
        except ImportError:
            _sql_validator = False  # sqlglot not installed
    return _sql_validator


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
    """Ejecuta SQL. SELECT/WITH/SHOW/DESCRIBE devuelve filas; INSERT/UPDATE devuelve {\"status\":\"ok\"}."""
    if not query or not query.strip():
        return json.dumps({"error": "Query vacío."})
    q = query.strip()
    validator = _get_sql_validator()
    if validator:
        ok, err = validator.validate(q)
        if not ok:
            return json.dumps({"error": err})
    else:
        # Fallback when sqlglot not installed
        import re

        blocked = re.compile(
            r"\b(DROP|TRUNCATE|ATTACH|DETACH|COPY|EXPORT|IMPORT|ALTER)\b", re.IGNORECASE
        )
        if blocked.search(q):
            return json.dumps({"error": "Comando no permitido por política de seguridad."})
    try:
        if q.upper().startswith(("SELECT", "WITH", "SHOW", "DESCRIBE")):
            raw = db.query(q)
            # Cuando hay muchas filas, serializar como markdown compacto para el LLM
            # (spec Pipeline_de_Datos_Zero-Copy_con_PyArrow.md — LLMContextSerializer)
            try:
                from duckclaw.data.arrow_bridge import LLMContextSerializer, arrow_available  # noqa: PLC0415
                if arrow_available():
                    rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
                    if isinstance(rows, list) and len(rows) > 30:
                        return LLMContextSerializer.from_json(raw, max_rows=30)
            except Exception:
                pass
            return raw
        db.execute(q)
        return json.dumps({"status": "ok"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def inspect_schema(db: Any) -> str:
    """Retorna la estructura de la DB: lista de tablas con sus columnas en formato legible."""
    try:
        tables = json.loads(
            db.query(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            )
        )
        if not tables or not isinstance(tables, list):
            return "No hay tablas en la base de datos."
        lines = []
        for t in tables:
            name = t.get("table_name") if isinstance(t, dict) else None
            if not name:
                continue
            name_esc = str(name).replace("'", "''")
            cols_raw = json.loads(db.query(
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_schema = 'main' AND table_name = '{name_esc}' ORDER BY ordinal_position"
            ))
            col_names = [c.get("column_name", "") for c in cols_raw if isinstance(c, dict)]
            lines.append(f"- {name}: {', '.join(col_names)}")
        return "Tablas disponibles:\n" + "\n".join(lines)
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

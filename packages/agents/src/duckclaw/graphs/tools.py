"""Herramientas genéricas que usan el motor C++ DuckClaw."""

from __future__ import annotations

import json
import re
from typing import Any

from duckclaw.utils.logger import log_tool_execution_sync

# Solo lectura: consultas que no modifican datos/estructura.
_READ_ONLY = re.compile(r"^\s*(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN|PRAGMA)\s", re.IGNORECASE)

# Operaciones destructivas o de acceso al sistema de archivos — siempre bloqueadas.
# Nota: dejamos CREATE/DELETE/UPDATE/INSERT/ALTER permitidos para admin_sql (si no está en read-only).
_BLOCKED = re.compile(r"\b(ATTACH|DETACH|COPY|EXPORT|IMPORT)\b", re.IGNORECASE)

# ALTER estructura se permite en admin_sql. En read_sql se bloquea por tipo de consulta.
# (Aquí solo mantenemos el regex para compatibilidad interna si existiera.)
_ALTER_BLOCKED = re.compile(r"^\s*ALTER\s", re.IGNORECASE)

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


@log_tool_execution_sync(name="read_sql")
def read_sql(db: Any, query: str) -> str:
    """Solo lectura SQL: SELECT/WITH/SHOW/DESCRIBE/EXPLAIN/PRAGMA. Retorna filas como JSON/string."""
    if not query or not query.strip():
        return json.dumps({"error": "Query vacío."})
    q = query.strip()
    if _BLOCKED.search(q):
        blocked = re.search(r"\b(ATTACH|DETACH|COPY|EXPORT|IMPORT)\b", q, re.IGNORECASE)
        cmd = blocked.group(0).upper() if blocked else "comando"
        return json.dumps({"error": f"{cmd} no está permitido por política de seguridad."})
    if not _READ_ONLY.search(q):
        return json.dumps({"error": "read_sql es solo lectura. Usa admin_sql para escrituras (INSERT/UPDATE/DELETE/CREATE, etc.)."})
    try:
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
    except Exception as e:
        return json.dumps({"error": str(e)})


def admin_sql(db: Any, query: str) -> str:
    """Admin SQL: lectura + escrituras (INSERT/UPDATE/DELETE/CREATE/ALTER/...)."""
    if not query or not query.strip():
        return json.dumps({"error": "Query vacío."})
    q = query.strip()
    if _BLOCKED.search(q):
        blocked = re.search(r"\b(ATTACH|DETACH|COPY|EXPORT|IMPORT)\b", q, re.IGNORECASE)
        cmd = blocked.group(0).upper() if blocked else "comando"
        return json.dumps({"error": f"{cmd} no está permitido por política de seguridad."})
    try:
        if _READ_ONLY.search(q):
            raw = db.query(q)
            return raw

        # SingletonWriterBridge: encolar si Redis configurado (spec Auditoria_Arquitectura)
        try:
            from duckclaw.forge.homeostasis.singleton_writer import enqueue_write
            if enqueue_write(q):
                return json.dumps({"status": "ok", "queued": True})
        except Exception:
            pass
        db.execute(q)
        return json.dumps({"status": "ok"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_db_path(db: Any) -> str:
    """Retorna la ruta o nombre del archivo .duckdb al que tiene acceso el agente."""
    path = getattr(db, "_path", None) or getattr(db, "path", None)
    if path and str(path).strip() and str(path) != ":memory:":
        return str(path).strip()
    try:
        from duckclaw.gateway_db import get_gateway_db_path
        return get_gateway_db_path()
    except Exception:
        return "(ruta no disponible)"


@log_tool_execution_sync(name="inspect_schema")
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
            return "Sin tablas."
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
            lines.append(f"{name}: {', '.join(col_names)}")
        return "Tablas:\n" + "\n".join(lines)
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
            sql = (
                f"INSERT INTO {_MEMORY_TABLE} (key, value) VALUES ('{key_safe}', '{value_safe}') "
                f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP"
            )
            try:
                from duckclaw.forge.homeostasis.singleton_writer import enqueue_write
                if enqueue_write(sql):
                    return json.dumps({"status": "ok", "queued": True})
            except Exception:
                pass
            db.execute(sql)
            return json.dumps({"status": "ok"})
        if action == "delete":
            sql = f"DELETE FROM {_MEMORY_TABLE} WHERE key = '{key_safe}'"
            try:
                from duckclaw.forge.homeostasis.singleton_writer import enqueue_write
                if enqueue_write(sql):
                    return json.dumps({"status": "ok", "queued": True})
            except Exception:
                pass
            db.execute(sql)
        return json.dumps({"status": "ok"})
        return json.dumps({"error": f"action debe ser get, set o delete"})
    except Exception as e:
        return json.dumps({"error": str(e)})

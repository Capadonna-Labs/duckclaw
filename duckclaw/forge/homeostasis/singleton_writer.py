"""
SingletonWriterBridge — desacopla escrituras DuckDB para evitar colisiones de lock.

Spec: specs/Auditoria_Arquitectura_y_Mejoras_Prioridad_Alta.md

Uso:
  - Con Redis: DUCKCLAW_WRITE_QUEUE_URL=redis://localhost/0 → enqueue en duckdb_write_queue
  - Sin Redis: ejecución directa (fallback)
  - Consumidor: python -m duckclaw.forge.homeostasis.singleton_writer --consume
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

_QUEUE_KEY = "duckdb_write_queue"
_QUEUE_URL_ENV = "DUCKCLAW_WRITE_QUEUE_URL"
_DB_PATH_ENV = "DUCKCLAW_DB_PATH"


def _get_queue_url() -> Optional[str]:
    return os.environ.get(_QUEUE_URL_ENV, "").strip() or None


def _is_write_sql(sql: str) -> bool:
    """True si la sentencia es INSERT, UPDATE, DELETE o CREATE."""
    s = (sql or "").strip().upper()
    return any(s.startswith(kw) for kw in ("INSERT", "UPDATE", "DELETE", "CREATE", "REPLACE"))


def enqueue_write(sql: str, db_path: Optional[str] = None) -> bool:
    """
    Encola una escritura en Redis. Retorna True si se encoló, False si no hay Redis.
    """
    url = _get_queue_url()
    if not url:
        return False
    try:
        import redis
        r = redis.from_url(url)
        payload = json.dumps({"sql": sql, "db_path": db_path or os.environ.get(_DB_PATH_ENV, "")})
        r.lpush(_QUEUE_KEY, payload)
        return True
    except ImportError:
        return False
    except Exception:
        return False


def execute_write_direct(db: Any, sql: str) -> None:
    """Ejecuta la escritura directamente en DuckDB (usado por el consumidor)."""
    db.execute(sql)


class WriteQueueBridge:
    """
    Wrapper que intercepta db.execute(): si es escritura y hay Redis, encola;
    si no, ejecuta directamente.
    """

    def __init__(self, db: Any, db_path: Optional[str] = None):
        self._db = db
        self._db_path = db_path

    def execute(self, sql: str) -> None:
        if not _is_write_sql(sql):
            self._db.execute(sql)
            return
        if enqueue_write(sql, self._db_path):
            return  # Encolado, el consumidor lo ejecutará
        self._db.execute(sql)  # Fallback directo

    def query(self, sql: str) -> Any:
        return self._db.query(sql)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._db, name)


def run_consumer(db_path: Optional[str] = None, poll_interval: float = 0.5) -> None:
    """
    Consumidor: lee de Redis duckdb_write_queue y ejecuta escrituras en DuckDB.
    Ejecutar como proceso único (PM2: DuckClaw-DB-Writer).
    """
    url = _get_queue_url()
    if not url:
        print("DUCKCLAW_WRITE_QUEUE_URL no configurado. Salida.", file=sys.stderr)
        sys.exit(1)

    path = db_path or os.environ.get(_DB_PATH_ENV, "")
    if not path:
        from duckclaw.gateway_db import get_gateway_db_path
        path = get_gateway_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    from duckclaw import DuckClaw
    db = DuckClaw(path)

    try:
        import redis
        r = redis.from_url(url)
    except ImportError:
        print("redis no instalado. pip install redis", file=sys.stderr)
        sys.exit(1)

    print(f"DuckClaw-DB-Writer iniciado. DB: {path}", flush=True)
    while True:
        try:
            _, raw = r.brpop(_QUEUE_KEY, timeout=int(poll_interval))
            if raw:
                data = json.loads(raw)
                sql = data.get("sql", "")
                if sql:
                    db.execute(sql)
                    print(f"OK: {sql[:80]}...", flush=True)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
        time.sleep(0.01)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--consume", action="store_true", help="Ejecutar consumidor de cola")
    parser.add_argument("--db-path", default=None, help="Ruta a DuckDB")
    args = parser.parse_args()
    if args.consume:
        run_consumer(db_path=args.db_path)
    else:
        print("Uso: python -m duckclaw.forge.homeostasis.singleton_writer --consume")

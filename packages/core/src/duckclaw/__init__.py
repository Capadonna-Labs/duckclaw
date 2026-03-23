"""DuckClaw core: DuckDB bridge. Namespace merge con duckclaw-shared."""

import pkgutil

__path__ = pkgutil.extend_path(__path__, __name__)

try:
    from duckclaw._duckclaw import DuckClaw
except ImportError:
    import json
    from typing import Any

    import duckdb

    class DuckClaw:
        """Fallback DuckDB wrapper cuando el extension C++ no está compilado."""

        def __init__(self, db_path: str):
            self._path = db_path or ":memory:"
            self._con = duckdb.connect(self._path)

        def query(self, sql: str) -> str:
            result = self._con.execute(sql)
            rows = result.fetchall()
            names = [d[0] for d in result.description]
            out = [dict(zip(names, (str(v) for v in row))) for row in rows]
            return json.dumps(out, ensure_ascii=False)

        def execute(self, sql: str, params=None) -> Any:
            """Ejecuta SQL y devuelve filas vía fetchall() (API duckdb: execute devuelve la conexión)."""
            if params is not None:
                self._con.execute(sql, params)
            else:
                self._con.execute(sql)
            return self._con.fetchall()

        def get_version(self) -> str:
            return str(self._con.execute("SELECT version()").fetchone()[0])

__all__ = ["DuckClaw"]

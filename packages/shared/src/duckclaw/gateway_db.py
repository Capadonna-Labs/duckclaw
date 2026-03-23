"""
Ruta y acceso a la BD del API Gateway (microservicio services/api-gateway).

Usado por duckclaw.graphs.graph_server, forge, workers y scripts cuando necesitan
la misma DuckDB que usa el Gateway. Resuelve desde DUCKCLAW_DB_PATH o DUCKDB_PATH.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_gateway_db_singleton: Any = None


def get_gateway_db_path() -> str:
    """
    Ruta del archivo DuckDB que usa el API Gateway (services/api-gateway).
    Resuelve DUCKCLAW_DB_PATH, luego DUCKDB_PATH; por defecto db/duckclaw.duckdb.
    No resuelve a ruta absoluta; el caller puede hacer Path(path).resolve() si necesita.
    """
    path = os.environ.get("DUCKCLAW_DB_PATH", "").strip()
    if path:
        return path
    return os.environ.get("DUCKDB_PATH", "db/duckclaw.duckdb").strip() or "db/duckclaw.duckdb"


def get_gateway_db() -> Any:
    """
    Instancia DuckClaw apuntando a la misma ruta que el API Gateway (legacy / herramientas sin db inyectada).

    Preferir pasar la conexión de la bóveda activa cuando el contexto sea multi-vault.
    """
    global _gateway_db_singleton
    if _gateway_db_singleton is not None:
        return _gateway_db_singleton
    from duckclaw import DuckClaw

    path = get_gateway_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _gateway_db_singleton = DuckClaw(path)
    return _gateway_db_singleton

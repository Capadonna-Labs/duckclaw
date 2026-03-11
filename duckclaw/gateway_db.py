"""Ruta única de la .duckdb del DuckClaw-Gateway (Telegram + agentes SQL)."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _REPO_ROOT / "db" / "gateway.duckdb"


def get_gateway_db_path() -> str:
    """Ruta de la base de datos del Gateway.

    Si DUCKCLAW_DB_PATH está definida, se usa esa ruta (resuelta).
    Si no, se usa db/gateway.duckdb respecto a la raíz del repo.
    """
    p = os.environ.get("DUCKCLAW_DB_PATH", "").strip()
    if p:
        return str(Path(p).resolve())
    return str(_DEFAULT_DB)

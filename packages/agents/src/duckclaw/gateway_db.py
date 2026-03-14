"""Ruta única de la .duckdb del DuckClaw-Gateway (Telegram + agentes SQL)."""

from __future__ import annotations

import os
from pathlib import Path

# packages/agents/src/duckclaw/gateway_db.py -> 5 niveles hasta repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_DB = _REPO_ROOT / "db" / "gateway.duckdb"


def get_gateway_db_path() -> str:
    """Ruta de la base de datos del Gateway.

    Si DUCKCLAW_DB_PATH está definida, se usa esa ruta (resuelta).
    Si es relativa (ej. db/telegram.duckdb), se resuelve respecto a la raíz del repo.
    Si no, se usa db/gateway.duckdb respecto a la raíz del repo.
    """
    p = os.environ.get("DUCKCLAW_DB_PATH", "").strip()
    if p:
        path = Path(p)
        if not path.is_absolute():
            path = _REPO_ROOT / path
        return str(path.resolve())
    return str(_DEFAULT_DB)

#!/usr/bin/env python3
"""
Inserta o actualiza un usuario como admin en main.authorized_users (Telegram Guard / /team).

Usa la misma ruta DuckDB que el API Gateway (DUCKCLAW_DB_PATH).

Ejemplo (ajusta la ruta a tu PM2 / TheMind-Gateway):
  export DUCKCLAW_DB_PATH="/Users/.../duckclaw/db/private/1726618406/the_mind.duckdb"
  uv run python scripts/bootstrap_team_admin.py 1726618406 --username Juan

Si DuckDB devuelve lock (PM2 tiene abierta la misma .duckdb): ``pm2 stop TheMind-Gateway``,
ejecuta el script, luego ``pm2 start TheMind-Gateway``.

Caché Redis (si usas whitelist cacheada):
  redis-cli DEL "whitelist:default:1726618406"
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _redis_delete_whitelist_cache(*, tenant_id: str, user_id: str) -> None:
    tid = str(tenant_id or "default").strip() or "default"
    uid = str(user_id or "").strip()
    if not uid:
        return
    url = (os.environ.get("REDIS_URL") or os.environ.get("DUCKCLAW_REDIS_URL") or "").strip()
    if not url:
        return
    key = f"whitelist:{tid}:{uid}"
    try:
        import redis as redis_sync  # noqa: PLC0415

        client = redis_sync.Redis.from_url(url, decode_responses=True)
        client.delete(key)
        print(f"Redis: deleted {key}")
    except Exception as exc:
        print(f"Redis (aviso): no se pudo borrar caché: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap: primer admin en authorized_users")
    parser.add_argument("user_id", help="Telegram user_id o API user_id (ej. 1726618406)")
    parser.add_argument("--tenant", default="default", help="tenant_id (default: default)")
    parser.add_argument("--username", default="admin", help="Nombre mostrado en /team")
    parser.add_argument(
        "--db",
        default="",
        help="Ruta explícita a .duckdb (si no, usa DUCKCLAW_DB_PATH / get_gateway_db_path)",
    )
    args = parser.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "DUCKCLAW_REPO_ROOT" not in os.environ:
        os.environ["DUCKCLAW_REPO_ROOT"] = repo
    # core antes que shared: el paquete `duckclaw` con DuckClaw vive en duckclaw-core.
    sys.path[:0] = [
        os.path.join(repo, "packages", "core", "src"),
        os.path.join(repo, "packages", "shared", "src"),
    ]

    db_path = (args.db or os.environ.get("DUCKCLAW_DB_PATH") or "").strip()
    if not db_path:
        from duckclaw.gateway_db import get_gateway_db_path

        db_path = get_gateway_db_path()

    from duckclaw import DuckClaw

    uid = str(args.user_id).strip().replace("'", "''")[:128]
    tid = str(args.tenant).strip().replace("'", "''")[:128] or "default"
    un = str(args.username).strip().replace("'", "''")[:128] or "admin"

    db = DuckClaw(db_path)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS main.authorized_users (
            tenant_id VARCHAR,
            user_id VARCHAR,
            username VARCHAR,
            role VARCHAR DEFAULT 'user',
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (tenant_id, user_id)
        )
        """
    )
    db.execute(
        f"""
        INSERT INTO main.authorized_users (tenant_id, user_id, username, role)
        VALUES ('{tid}', '{uid}', '{un}', 'admin')
        ON CONFLICT (tenant_id, user_id) DO UPDATE SET
          username = EXCLUDED.username,
          role = 'admin',
          added_at = now()
        """
    )
    raw = db.query(
        f"SELECT user_id, username, role FROM main.authorized_users WHERE tenant_id='{tid}' AND user_id='{uid}' LIMIT 1"
    )
    rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
    print(f"OK: {rows!r}")
    print(f"Base: {db_path}")
    _redis_delete_whitelist_cache(tenant_id=tid, user_id=uid)
    print("Prueba: POST /team con user_id este valor; luego /team --add ...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Recrea la BD del Gateway desde cero: backup del archivo actual y nueva BD con schema completo.

Usa la misma ruta que el Gateway (get_gateway_db_path(), respeta .env).
Uso: python3 scripts/recreate_gateway_db.py
"""
import sys
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
try:
    from dotenv import load_dotenv
    load_dotenv(root / ".env")
except ImportError:
    pass

from duckclaw.sql_split import split_sql_statements


def main():
    from duckclaw.gateway_db import get_gateway_db_path
    from duckclaw import DuckClaw
    from duckclaw.vaults import ensure_registry as ensure_vault_registry

    db_path = get_gateway_db_path()
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    backup_path = None
    if path.is_file():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = path.parent / (path.name + f".bak.{ts}")
        path.rename(backup_path)
        backup_path = str(backup_path)
        print("Backup:", backup_path)

    db = DuckClaw(db_path)
    db.execute("SELECT 1")
    ensure_vault_registry()

    # Main: tablas que usa el Gateway desde el primer request
    db.execute("""
        CREATE TABLE IF NOT EXISTS api_conversation (
            session_id VARCHAR NOT NULL,
            worker_id VARCHAR NOT NULL,
            role VARCHAR NOT NULL,
            content TEXT,
            author_type VARCHAR DEFAULT 'AI',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS agent_config (
            key VARCHAR PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Telegram Guard: whitelist per tenant/user for authorization checks.
    db.execute("""
        CREATE TABLE IF NOT EXISTS main.authorized_users (
            tenant_id VARCHAR,
            user_id VARCHAR,
            username VARCHAR,
            role VARCHAR DEFAULT 'user',
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (tenant_id, user_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS main.user_shared_db_access (
            tenant_id VARCHAR NOT NULL,
            user_id VARCHAR NOT NULL,
            resource_key VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (tenant_id, user_id, resource_key)
        )
    """)

    # Finance_worker: schema + agent_beliefs + schema.sql
    db.execute("CREATE SCHEMA IF NOT EXISTS finance_worker")
    db.execute("""
        CREATE TABLE IF NOT EXISTS finance_worker.agent_beliefs (
            belief_key VARCHAR PRIMARY KEY,
            target_value REAL NOT NULL,
            observed_value REAL,
            threshold REAL NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    schema_sql = (root / "templates" / "workers" / "finanz" / "schema.sql").read_text(encoding="utf-8")
    for stmt in split_sql_statements(schema_sql):
        if stmt.strip():
            db.execute(stmt)

    print("BD nueva:", db_path)
    if backup_path:
        print("Backup anterior:", backup_path)


if __name__ == "__main__":
    main()

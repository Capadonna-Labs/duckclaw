#!/usr/bin/env python3
"""Muestra dónde escribe el Gateway API (Telegram → n8n → /api/v1/agent/.../chat)."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

def main():
    try:
        from duckclaw.gateway_db import get_gateway_db_path
        db_path = get_gateway_db_path()
    except Exception:
        db_path = str(_root / "db" / "gateway.duckdb")
    print("Gateway API (Telegram/n8n chat) escribe en:")
    print("  ", db_path)
    print("  existe:", Path(db_path).is_file())
    if Path(db_path).is_file():
        try:
            import duckdb
            c = duckdb.connect(db_path, read_only=True)
            tabs = c.execute("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema','pg_catalog')
                ORDER BY table_schema, table_name
            """).fetchall()
            print("  tablas:")
            for s, t in tabs:
                try:
                    n = c.execute(f'SELECT COUNT(*) FROM "{s}"."{t}"').fetchone()[0]
                    print(f"    {s}.{t}: {n}")
                except Exception as e:
                    print(f"    {s}.{t}: (error al contar: {e})")
            c.close()
        except Exception as e:
            print("  error al leer:", e)
    print()
    print("Para inspeccionar: python3 scripts/inspect_telegram_db.py", db_path)

if __name__ == "__main__":
    main()

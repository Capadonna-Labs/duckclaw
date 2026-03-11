#!/usr/bin/env python3
"""Inspecciona telegram.duckdb: tablas, transacciones, presupuestos, cuentas."""
import sys
from pathlib import Path

db_path = Path(__file__).resolve().parent.parent / "db" / "telegram.duckdb"
if len(sys.argv) > 1:
    db_path = Path(sys.argv[1])

if not db_path.is_file():
    print(f"No existe: {db_path}")
    sys.exit(1)

from duckdb import connect
db = connect(str(db_path), read_only=True)

print("=== TABLAS ===")
tables = db.execute("""
    SELECT table_schema, table_name 
    FROM information_schema.tables 
    WHERE table_schema NOT IN ('information_schema','pg_catalog') 
    ORDER BY table_schema, table_name
""").fetchall()
for s, t in tables:
    n = db.execute(f'SELECT COUNT(*) FROM "{s}"."{t}"').fetchone()[0]
    print(f"  {s}.{t}: {n} filas")

print("\n=== MUESTRA finance_worker (cuentas, transactions) ===")
for s, t in tables:
    if s == "finance_worker":
        n = db.execute(f'SELECT COUNT(*) FROM "{s}"."{t}"').fetchone()[0]
        print(f"\n{s}.{t} ({n} filas):")
        if n > 0:
            rows = db.execute(f'SELECT * FROM "{s}"."{t}" LIMIT 10').fetchall()
            for row in rows:
                print(" ", row)
            if n > 10:
                print("  ...")

print("\n=== OTRAS TABLAS CON DATOS (api_conversation, etc.) ===")
for s, t in tables:
    if s in ("main", "public") or "conversation" in t or "agent" in t:
        n = db.execute(f'SELECT COUNT(*) FROM "{s}"."{t}"').fetchone()[0]
        if n > 0:
            print(f"\n{s}.{t}: {n} filas")
            rows = db.execute(f'SELECT * FROM "{s}"."{t}" LIMIT 2').fetchall()
            for row in rows:
                print(" ", row)

db.close()
print("\nOK")

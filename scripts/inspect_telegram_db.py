#!/usr/bin/env python3
"""Inspecciona la DB del Gateway (gateway.duckdb por defecto): tablas, transacciones, presupuestos, cuentas."""
import sys
from pathlib import Path

# Asegurar import del paquete cuando se ejecuta desde repo root
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    from duckclaw.gateway_db import get_gateway_db_path
    _default_path = get_gateway_db_path()
except Exception:
    _default_path = str(_root / "db" / "gateway.duckdb")

db_path = Path(_default_path) if len(sys.argv) <= 1 else Path(sys.argv[1])

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

print("\n=== MUESTRA finance_worker (cuentas, transactions, presupuestos, deudas) ===")
# Asegurar que miramos todas las tablas esperadas de Finanz (aunque no estén en information_schema aún)
finanz_tables = ["agent_beliefs", "categories", "transactions", "cuentas", "presupuestos", "deudas"]
for s, t in tables:
    if s == "finance_worker":
        finanz_tables = [x for x in finanz_tables if (s, x) != (s, t)]
        n = db.execute(f'SELECT COUNT(*) FROM "{s}"."{t}"').fetchone()[0]
        print(f"\n{s}.{t} ({n} filas):")
        if n > 0:
            rows = db.execute(f'SELECT * FROM "{s}"."{t}" LIMIT 10').fetchall()
            for row in rows:
                print(" ", row)
            if n > 10:
                print("  ...")
for t in finanz_tables:
    try:
        n = db.execute(f'SELECT COUNT(*) FROM finance_worker."{t}"').fetchone()[0]
        print(f"\nfinance_worker.{t} ({n} filas):")
        if n > 0:
            for row in db.execute(f'SELECT * FROM finance_worker."{t}" LIMIT 10').fetchall():
                print(" ", row)
    except Exception as e:
        print(f"\nfinance_worker.{t}: (tabla no existe aún: {e})")

print("\n=== OTRAS TABLAS CON DATOS (api_conversation, etc.) ===")
for s, t in tables:
    if s in ("main", "public") or "conversation" in t or "agent" in t:
        try:
            n = db.execute(f'SELECT COUNT(*) FROM "{s}"."{t}"').fetchone()[0]
        except Exception as e:
            print(f"\n{s}.{t}: (error al contar: {e})")
            continue
        if n > 0:
            print(f"\n{s}.{t}: {n} filas")
            try:
                rows = db.execute(f'SELECT * FROM "{s}"."{t}" LIMIT 2').fetchall()
                for row in rows:
                    print(" ", row)
            except Exception as e:
                print("  (error al leer filas:", e, ")")

db.close()
print("\nOK")

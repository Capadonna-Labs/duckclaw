#!/bin/bash
# Ejecutar en Mac: bash -s < scripts/remote_inspect_db.sh
# O: ssh user@mac 'bash -s' < scripts/remote_inspect_db.sh
set -e
cd /Users/juanjosearevalocamargo/Desktop/duckclaw
DB=db/telegram.duckdb
export PATH="/opt/homebrew/bin:$PATH"
.venv/bin/python3 << 'PY'
import duckdb
db = duckdb.connect('db/telegram.duckdb', read_only=True)
r = db.execute("""
    SELECT table_schema, table_name 
    FROM information_schema.tables 
    WHERE table_schema NOT IN ('information_schema','pg_catalog') 
    ORDER BY 1, 2
""").fetchall()
print("=== TABLAS en telegram.duckdb ===")
for s, t in r:
    n = db.execute('SELECT COUNT(*) FROM "' + s + '"."' + t + '"').fetchone()[0]
    print("  %s.%s: %d filas" % (s, t, n))
print("\n=== finance_worker (transacciones, presupuestos, cuentas) ===")
for s, t in r:
    if s == "finance_worker":
        n = db.execute('SELECT COUNT(*) FROM "' + s + '"."' + t + '"').fetchone()[0]
        print("\n%s.%s (%d filas):" % (s, t, n))
        if n > 0:
            df = db.execute('SELECT * FROM "' + s + '"."' + t + '" LIMIT 8').fetchdf()
            print(df.to_string())
            if n > 8:
                print("  ...")
print("\n=== Otras tablas con datos ===")
for s, t in r:
    if s not in ("finance_worker",) and "conversation" in t or "checkpoint" in t:
        n = db.execute('SELECT COUNT(*) FROM "' + s + '"."' + t + '"').fetchone()[0]
        if n > 0:
            print("  %s.%s: %d filas" % (s, t, n))
db.close()
print("\nOK")
PY

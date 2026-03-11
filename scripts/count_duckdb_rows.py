#!/usr/bin/env python3
"""Cuenta filas en archivos .duckdb para encontrar el más poblado."""
import duckdb
import os
import sys

def count_db(path: str) -> int:
    try:
        c = duckdb.connect(path, read_only=True)
        tables = c.execute(
            """SELECT table_schema, table_name FROM information_schema.tables 
               WHERE table_schema NOT IN ('information_schema', 'pg_catalog')"""
        ).fetchall()
        total = 0
        for sch, tbl in tables:
            try:
                cnt = c.execute(f'SELECT count(*) FROM "{sch}"."{tbl}"').fetchone()[0]
                total += cnt
            except Exception:
                pass
        return total
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        return -1

if __name__ == "__main__":
    paths = sys.argv[1:] if len(sys.argv) > 1 else []
    if not paths:
        print("Uso: python count_duckdb_rows.py <path1> [path2] ...")
        sys.exit(1)
    for p in paths:
        if os.path.exists(p):
            n = count_db(p)
            print(f"{p}: {n} rows")
        else:
            print(f"{p}: no existe")

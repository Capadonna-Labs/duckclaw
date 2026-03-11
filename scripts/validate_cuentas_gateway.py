#!/usr/bin/env python3
"""Valida el contenido de la tabla cuentas en la .duckdb que usa DuckClaw-Gateway."""
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

    if len(sys.argv) > 1:
        db_path = str(Path(sys.argv[1]).resolve())

    if not Path(db_path).is_file():
        print(f"DB no encontrada: {db_path}")
        print("El Gateway usa esta ruta (o DUCKCLAW_DB_PATH si está definida).")
        sys.exit(1)

    import duckdb
    conn = duckdb.connect(db_path, read_only=True)

    # Buscar tabla cuentas en cualquier esquema
    schemas_tables = conn.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_name = 'cuentas'
        ORDER BY table_schema
    """).fetchall()

    if not schemas_tables:
        print(f"DB: {db_path}")
        print("No existe ninguna tabla 'cuentas' en esta base.")
        all_tables = conn.execute("""
            SELECT table_schema, table_name FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema','pg_catalog')
            ORDER BY 1, 2
        """).fetchall()
        print("Tablas presentes:", [f"{s}.{t}" for s, t in all_tables])
        conn.close()
        sys.exit(0)

    print(f"DB: {db_path}\n")
    for schema, table in schemas_tables:
        full = f'"{schema}"."{table}"'
        print(f"=== {schema}.cuentas ===")
        try:
            cols = conn.execute(f"DESCRIBE {full}").fetchall()
            print("Columnas:", [c[0] for c in cols])
        except Exception as e:
            print("Error DESCRIBE:", e)
            continue
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {full}").fetchone()[0]
            print(f"Filas: {n}")
        except Exception as e:
            print("Error COUNT:", e)
            continue
        if n > 0:
            try:
                rows = conn.execute(f"SELECT * FROM {full} ORDER BY id LIMIT 20").fetchall()
                col_names = [d[0] for d in conn.execute(f"DESCRIBE {full}").fetchall()]
                print("Muestra (id, name, balance, currency, updated_at):")
                for row in rows:
                    print(" ", dict(zip(col_names, row)))
            except Exception as e:
                print("Error SELECT:", e)
        print()
    conn.close()
    print("OK")

if __name__ == "__main__":
    main()

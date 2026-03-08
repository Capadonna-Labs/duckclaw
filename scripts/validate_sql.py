#!/usr/bin/env python3
"""
Valida sintaxis SQL de archivos schema.sql usando sqlglot.

Spec: specs/Pipeline_de_Despliegue_Continuo_(CI/CD)_para_Arquitectura_Distribuida.md
Uso: python scripts/validate_sql.py
Exit 0 si todo OK, 1 si hay errores de parseo.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    sql_files = list((root / "templates" / "workers").rglob("schema.sql"))
    datalake = root / "datalake"
    if datalake.is_dir():
        sql_files.extend(datalake.glob("*.sql"))
    sql_files = [f for f in sql_files if f.is_file()]

    try:
        import sqlglot
    except ImportError:
        print("Error: sqlglot no instalado. Ejecuta: uv sync --extra dev", file=sys.stderr)
        return 1

    errors: list[tuple[Path, str]] = []
    validated_count = 0
    for path in sorted(set(sql_files)):
        try:
            sql = path.read_text(encoding="utf-8")
            # Skip empty or comment-only
            if not sql.strip():
                continue
            sqlglot.parse(sql, dialect="duckdb")
            validated_count += 1
        except Exception as e:
            errors.append((path, str(e)))

    if errors:
        for path, msg in errors:
            print(f"ERROR {path}: {msg}", file=sys.stderr)
        return 1
    print(f"OK: {validated_count} archivo(s) SQL validado(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

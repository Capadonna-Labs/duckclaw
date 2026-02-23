#!/usr/bin/env python3
"""Inicializa la base de datos de finanzas e inventario (Capa de Negocio IoTCoreLabs).

Crea vfs/finance/store.duckdb con tablas inventory y transactions.
Usa rutas absolutas para evitar errores en entornos como Mac Mini.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo root (absoluto) y path para importar duckclaw
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(REPO_ROOT))
VFS_FINANCE = REPO_ROOT / "vfs" / "finance"
STORE_DB_PATH = VFS_FINANCE / "store.duckdb"


def main() -> int:
    VFS_FINANCE.mkdir(parents=True, exist_ok=True)
    db_path_abs = str(STORE_DB_PATH)

    try:
        import duckclaw
    except ImportError:
        print("Error: duckclaw no instalado. Ejecuta: pip install -e . --no-build-isolation", file=sys.stderr)
        return 1

    db = duckclaw.DuckClaw(db_path_abs)

    db.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            sku VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            category VARCHAR,
            size VARCHAR,
            cost_price DOUBLE,
            sale_price DOUBLE,
            stock_count INTEGER NOT NULL DEFAULT 0,
            last_updated TIMESTAMP DEFAULT now()
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id VARCHAR NOT NULL,
            timestamp TIMESTAMP DEFAULT now(),
            type VARCHAR NOT NULL,
            amount DOUBLE NOT NULL,
            sku_related VARCHAR,
            payment_method VARCHAR,
            notes VARCHAR
        )
    """)

    # 3 registros de ejemplo "Tallas Grandes"
    samples = [
        ("BLUSA-XL", "Blusa XL", "Tallas Grandes", "XL", 12.50, 24.99, 10),
        ("PANTALON-2XL", "Pantalón 2XL", "Tallas Grandes", "2XL", 18.00, 39.99, 8),
        ("CAMISA-XL", "Camisa XL", "Tallas Grandes", "XL", 15.00, 32.00, 5),
    ]
    for sku, name, category, size, cost_price, sale_price, stock_count in samples:
        esc = lambda s: str(s).replace("'", "''")
        db.execute(
            f"""
            INSERT INTO inventory (sku, name, category, size, cost_price, sale_price, stock_count)
            VALUES ('{esc(sku)}', '{esc(name)}', '{esc(category)}', '{esc(size)}', {cost_price}, {sale_price}, {stock_count})
            ON CONFLICT (sku) DO UPDATE SET
                name = EXCLUDED.name, category = EXCLUDED.category, size = EXCLUDED.size,
                cost_price = EXCLUDED.cost_price, sale_price = EXCLUDED.sale_price,
                stock_count = EXCLUDED.stock_count, last_updated = now()
            """
        )

    print(f"Base de datos creada: {db_path_abs}")
    print("Tablas: inventory, transactions. 3 ítems de ejemplo (Tallas Grandes) insertados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

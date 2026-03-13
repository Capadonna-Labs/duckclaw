"""Herramientas de la Capa de Negocio: finanzas e inventario (IoTCoreLabs)."""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from langchain_core.tools import tool


def _esc(s: str) -> str:
    return str(s).replace("'", "''")


def _inspect_schema_impl(db: Any) -> str:
    """Obtiene el esquema de la DB. Usa get_schema_context si existe, sino consulta information_schema."""
    if hasattr(db, "get_schema_context") and callable(getattr(db, "get_schema_context")):
        return db.get_schema_context()
    try:
        tables = json.loads(
            db.query(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            )
        )
        out = []
        for t in tables if isinstance(tables, list) else []:
            name = t.get("table_name") if isinstance(t, dict) else None
            if not name:
                continue
            name_esc = str(name).replace("'", "''")
            cols = db.query(
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_schema = 'main' AND table_name = '{name_esc}' ORDER BY ordinal_position"
            )
            out.append({"table": name, "columns": json.loads(cols)})
        return json.dumps(out, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def build_store_tools(
    store_db: Any,
    console: Optional[Any] = None,
) -> list[Any]:
    """Construye las herramientas de tienda (inspect_schema, register_sale, check_inventory, record_expense)."""

    def _log_db(sql: str, count: int = 0) -> None:
        if console is not None and hasattr(console, "print_db_action"):
            console.print_db_action(sql, count)

    @tool
    def inspect_schema() -> str:
        """Returns the database schema (tables, columns, relations). Use this before writing SQL."""
        return _inspect_schema_impl(store_db)

    @tool
    def register_sale(item_name: str, size: str, price: float, method: str) -> str:
        """Registra una venta: busca el producto por nombre y talla, resta 1 al stock y registra la transacción.
        item_name: nombre del producto (ej. Blusa, Pantalón). size: talla (ej. XL, 2XL). price: precio de venta. method: método de pago (ej. efectivo, tarjeta, transferencia)."""
        try:
            name_esc, size_esc = _esc(item_name), _esc(size)
            sql_find = (
                f"SELECT sku, stock_count FROM inventory WHERE LOWER(name) LIKE LOWER('%{name_esc}%') AND LOWER(TRIM(size)) = LOWER('{size_esc}') LIMIT 1"
            )
            rows = store_db.query(sql_find)
            _log_db(sql_find, 1)
            data = json.loads(rows) if isinstance(rows, str) else rows
            if not data:
                return f"Error: No se encontró producto con nombre '{item_name}' y talla '{size}'."
            sku = data[0].get("sku")
            stock = int(data[0].get("stock_count", 0))
            if stock < 1:
                return f"Error: Sin stock para {item_name} ({size})."
            store_db.execute(
                f"UPDATE inventory SET stock_count = stock_count - 1, last_updated = CURRENT_TIMESTAMP WHERE sku = '{_esc(sku)}'"
            )
            _log_db("UPDATE inventory SET stock_count = ...", 1)
            tx_id = str(uuid.uuid4())
            store_db.execute(
                f"INSERT INTO transactions (id, type, amount, sku_related, payment_method, notes) "
                f"VALUES ('{tx_id}', 'SALE', {float(price)}, '{_esc(sku)}', '{_esc(method)}', 'Venta registrada por agente')"
            )
            _log_db("INSERT INTO transactions (SALE) ...", 1)
            return f"Venta registrada: {item_name} {size} a {price} ({method}). SKU={sku}. Stock restante: {stock - 1}."
        except Exception as e:
            return f"Error al registrar venta: {e}"

    @tool
    def check_inventory(name_filter: Optional[str] = None, size_filter: Optional[str] = None) -> str:
        """Consulta el inventario. Puedes filtrar por nombre (name_filter) y/o por talla (size_filter).
        Deja ambos en blanco para listar todo el inventario."""
        try:
            where_parts = []
            if name_filter and str(name_filter).strip():
                where_parts.append(f"LOWER(name) LIKE LOWER('%{_esc(str(name_filter).strip())}%')")
            if size_filter and str(size_filter).strip():
                where_parts.append(f"LOWER(TRIM(size)) = LOWER('{_esc(str(size_filter).strip())}')")
            where = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
            sql = f"SELECT sku, name, category, size, sale_price, stock_count, last_updated FROM inventory{where} ORDER BY name, size"
            rows = store_db.query(sql)
            _log_db(sql, 0)
            data = json.loads(rows) if isinstance(rows, str) else rows
            if not data:
                return "No hay productos que coincidan con el filtro." if where_parts else "Inventario vacío."
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Error al consultar inventario: {e}"

    @tool
    def record_expense(
        amount: float,
        expense_type: str,
        payment_method: str = "",
        notes: str = "",
    ) -> str:
        """Registra un gasto. expense_type debe ser 'BUSINESS' (arriendo, servicios, negocio) o 'PERSONAL' (gastos personales).
        amount: monto. payment_method: método de pago. notes: descripción opcional."""
        try:
            t = str(expense_type).strip().upper()
            if t not in ("BUSINESS", "PERSONAL"):
                return "Error: expense_type debe ser 'BUSINESS' o 'PERSONAL'."
            tx_id = str(uuid.uuid4())
            store_db.execute(
                f"INSERT INTO transactions (id, type, amount, sku_related, payment_method, notes) "
                f"VALUES ('{tx_id}', 'EXPENSE_{t}', {float(amount)}, NULL, '{_esc(payment_method)}', '{_esc(notes)}')"
            )
            _log_db("INSERT INTO transactions (EXPENSE_...) ...", 1)
            return f"Gasto registrado: {amount} ({t}) - {notes or payment_method or 'Sin detalle'}."
        except Exception as e:
            return f"Error al registrar gasto: {e}"

    return [inspect_schema, register_sale, check_inventory, record_expense]

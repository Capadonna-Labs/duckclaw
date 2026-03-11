"""
QuoteEngine — Core matemático: precios, descuentos, IVA, persistencia.

Spec: specs/Motor_Cotizacion_Omnicanal_QuoteEngine.md
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from duckclaw.forge.quotes.schema import QUOTES_DIR, ensure_quotes_schema


def _safe_esc(s: str) -> str:
    return str(s or "").replace("'", "''")[:256]


def _get_price(db: Any, schema: str, sku: str) -> Optional[Decimal]:
    """Obtiene precio base de catalog_items o products."""
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in schema.strip()) or "main"
    sku_esc = _safe_esc(sku)
    for table, col in [("catalog_items", "sku"), ("products", "id")]:
        try:
            if table == "catalog_items":
                r = db.query(
                    f"SELECT price FROM {safe}.{table} WHERE sku = '{sku_esc}' LIMIT 1"
                )
            else:
                try:
                    int(sku)
                    r = db.query(
                        f"SELECT price FROM {safe}.products WHERE id = {int(sku)} LIMIT 1"
                    )
                except ValueError:
                    r = db.query(
                        f"SELECT price FROM {safe}.products WHERE name LIKE '%{sku_esc}%' LIMIT 1"
                    )
            rows = json.loads(r) if isinstance(r, str) else (r or [])
            if rows and isinstance(rows[0], dict) and rows[0].get("price") is not None:
                p = rows[0]["price"]
                try:
                    return Decimal(str(p).replace(",", "."))
                except Exception:
                    pass
        except Exception:
            continue
    return None


def generate_quote(
    db: Any,
    items: list[dict],
    user_id: str,
    customer_name: str = "",
    schema: str = "powerseal_worker",
) -> dict:
    """
    Calcula cotización: valida precios, aplica descuento (>100 uds), IVA 19%.
    Persiste en quotes. Retorna QuoteData.
    """
    ensure_quotes_schema(db)
    user_id = (user_id or "").strip() or "unknown"
    customer_name = (customer_name or "").strip() or user_id

    line_items = []
    subtotal = Decimal("0")
    total_qty = 0

    for it in items or []:
        sku = str(it.get("sku") or it.get("id") or "").strip()
        qty = int(it.get("quantity") or it.get("qty") or 1)
        if not sku or qty < 1:
            continue
        price = _get_price(db, schema, sku)
        if price is None:
            price = Decimal("0")
        line_total = price * qty
        line_items.append({
            "sku": sku,
            "quantity": qty,
            "unit_price": float(price),
            "line_total": float(line_total),
        })
        subtotal += line_total
        total_qty += qty

    if not line_items:
        return {"error": "No hay ítems válidos para cotizar.", "quote_id": None}

    # Descuento: >100 unidades → 5%
    discount_pct = Decimal("0.05") if total_qty > 100 else Decimal("0")
    discount = subtotal * discount_pct

    # IVA 19% Colombia (sobre subtotal - descuento)
    tax_base = subtotal - discount
    tax_pct = Decimal("0.19")
    tax = tax_base * tax_pct

    total = tax_base + tax

    quote_id = f"COT-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()[:6]}"
    items_json = json.dumps(line_items, ensure_ascii=False)
    sub_esc = _safe_esc(str(subtotal))
    disc_esc = _safe_esc(str(discount))
    tax_esc = _safe_esc(str(tax))
    tot_esc = _safe_esc(str(total))
    uid_esc = _safe_esc(user_id)
    name_esc = _safe_esc(customer_name)
    items_esc = _safe_esc(items_json)
    qid_esc = _safe_esc(quote_id)

    try:
        db.execute(f"""
            INSERT INTO quotes (quote_id, user_id, customer_name, items, subtotal, discount, tax, total_amount, currency, status)
            VALUES ('{qid_esc}', '{uid_esc}', '{name_esc}', '{items_esc}', {sub_esc}, {disc_esc}, {tax_esc}, {tot_esc}, 'COP', 'generated')
        """)
    except Exception as e:
        return {"error": str(e), "quote_id": None}

    return {
        "quote_id": quote_id,
        "user_id": user_id,
        "customer_name": customer_name,
        "items": line_items,
        "subtotal": float(subtotal),
        "discount": float(discount),
        "discount_pct": float(discount_pct) * 100,
        "tax": float(tax),
        "tax_pct": 19,
        "total_amount": float(total),
        "currency": "COP",
        "status": "generated",
    }

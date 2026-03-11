"""Skill: quote_engine — Motor de cotización (precios, descuentos, IVA). Spec: Motor_Cotizacion_Omnicanal."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool


def get_tools(db: Any, schema_name: str, spec: Any = None) -> list:
    from duckclaw.forge.quotes.engine import generate_quote

    def quote_engine(
        items: str,
        user_id: str,
        customer_name: str = "",
    ) -> str:
        """
        Genera una cotización formal. items: JSON array [{sku, quantity}]. user_id: teléfono o email del lead.
        """
        try:
            parsed = json.loads(items) if isinstance(items, str) else items
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "items debe ser un JSON array: [{\"sku\": \"X\", \"quantity\": 5}]"})
        if not isinstance(parsed, list):
            return json.dumps({"error": "items debe ser una lista de ítems."})
        result = generate_quote(db, parsed, user_id, customer_name, schema_name)
        return json.dumps(result, ensure_ascii=False)

    return [
        StructuredTool.from_function(
            quote_engine,
            name="quote_engine",
            description="Genera cotización formal con precios, descuentos (>100 uds) e IVA 19%. items: JSON [{\"sku\": \"3121AI\", \"quantity\": 50}]. user_id: teléfono/email del cliente.",
        )
    ]

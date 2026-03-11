"""Skill: document_dispatcher — Envía cotización a n8n (Email, WhatsApp, CRM). Spec: Motor_Cotizacion_Omnicanal."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool


def get_tools(db: Any, schema_name: str, spec: Any = None) -> list:
    from duckclaw.forge.quotes.dispatcher import dispatch_quote_to_n8n

    def document_dispatcher(
        quote_data: str,
        delivery_preferences: str = "",
    ) -> str:
        """
        Envía la cotización al sistema de distribución (n8n). quote_data: JSON de QuoteEngine.
        delivery_preferences: "email", "whatsapp" o vacío (n8n decide).
        """
        try:
            data = json.loads(quote_data) if isinstance(quote_data, str) else quote_data
        except (json.JSONDecodeError, TypeError):
            return "Error: quote_data debe ser el JSON retornado por quote_engine."
        if not isinstance(data, dict):
            return "Error: quote_data inválido."
        return dispatch_quote_to_n8n(db, data, delivery_preferences=delivery_preferences or None)

    return [
        StructuredTool.from_function(
            document_dispatcher,
            name="document_dispatcher",
            description="Envía la cotización generada a n8n (Email, WhatsApp, CRM). Usa después de quote_engine. quote_data: JSON de la cotización. delivery_preferences: canal preferido (opcional).",
        )
    ]

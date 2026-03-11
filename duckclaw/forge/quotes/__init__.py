"""
Motor de Cotización Omnicanal (QuoteEngine).

Spec: specs/Motor_Cotizacion_Omnicanal_QuoteEngine.md
"""

from duckclaw.forge.quotes.schema import ensure_quotes_schema
from duckclaw.forge.quotes.engine import generate_quote
from duckclaw.forge.quotes.dispatcher import dispatch_quote_to_n8n

__all__ = ["ensure_quotes_schema", "generate_quote", "dispatch_quote_to_n8n"]

"""
Schema: tabla quotes y directorio de PDFs.

Spec: specs/Motor_Cotizacion_Omnicanal_QuoteEngine.md
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

QUOTES_DIR = Path(os.environ.get("DUCKCLAW_QUOTES_DIR", "/tmp/quotes"))


def ensure_quotes_schema(db: Any, schema: str = "main") -> None:
    """Crea tabla quotes si no existe."""
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in schema.strip()) or "main"
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS {safe}.quotes (
            quote_id VARCHAR PRIMARY KEY,
            user_id VARCHAR,
            customer_name VARCHAR,
            items JSON,
            subtotal DECIMAL,
            discount DECIMAL DEFAULT 0,
            tax DECIMAL DEFAULT 0,
            total_amount DECIMAL,
            currency VARCHAR DEFAULT 'COP',
            status VARCHAR DEFAULT 'generated',
            pdf_path VARCHAR,
            download_token VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    QUOTES_DIR.mkdir(parents=True, exist_ok=True)

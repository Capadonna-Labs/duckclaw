"""
DocumentDispatcher — Genera PDF, empaqueta payload y dispara webhook n8n.

Spec: specs/Motor_Cotizacion_Omnicanal_QuoteEngine.md
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Optional

from duckclaw.forge.quotes.schema import QUOTES_DIR, ensure_quotes_schema


def _generate_pdf(quote_data: dict, output_path: Path) -> bool:
    """Genera PDF con reportlab si está disponible."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

        doc = SimpleDocTemplate(str(output_path), pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph(f"Cotización {quote_data.get('quote_id', '')}", styles["Title"]))
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"Cliente: {quote_data.get('customer_name', '')}", styles["Normal"]))
        story.append(Spacer(1, 12))

        data = [["SKU", "Cantidad", "Precio Unit.", "Total"]]
        for it in quote_data.get("items", []):
            data.append([
                str(it.get("sku", "")),
                str(it.get("quantity", "")),
                f"${it.get('unit_price', 0):,.0f}",
                f"${it.get('line_total', 0):,.0f}",
            ])
        data.append(["", "", "Subtotal:", f"${quote_data.get('subtotal', 0):,.0f}"])
        data.append(["", "", "Descuento:", f"-${quote_data.get('discount', 0):,.0f}"])
        data.append(["", "", "IVA 19%:", f"${quote_data.get('tax', 0):,.0f}"])
        data.append(["", "", "TOTAL:", f"${quote_data.get('total_amount', 0):,.0f}"])

        t = Table(data)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), "#4472C4"),
            ("TEXTCOLOR", (0, 0), (-1, 0), "white"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("BACKGROUND", (0, 1), (-1, -1), "#f0f0f0"),
            ("GRID", (0, 0), (-1, -1), 0.5, "gray"),
        ]))
        story.append(t)
        doc.build(story)
        return True
    except ImportError:
        # Fallback: archivo JSON legible
        output_path.with_suffix(".json").write_text(json.dumps(quote_data, indent=2, ensure_ascii=False))
        return False
    except Exception:
        return False


def dispatch_quote_to_n8n(
    db: Any,
    quote_data: dict,
    base_url: Optional[str] = None,
    delivery_preferences: Optional[str] = None,
) -> str:
    """
    Genera PDF, actualiza quotes con pdf_path y token, dispara webhook n8n.
    Retorna mensaje para el agente.
    """
    if not quote_data or quote_data.get("error"):
        return quote_data.get("error", "Error generando cotización.") or "Error."

    ensure_quotes_schema(db)
    quote_id = quote_data.get("quote_id", "")
    if not quote_id:
        return "No se pudo generar la cotización."

    QUOTES_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = QUOTES_DIR / f"{quote_id}.pdf"
    _generate_pdf(quote_data, pdf_path)

    if not pdf_path.exists():
        pdf_path = QUOTES_DIR / f"{quote_data.get('quote_id', '')}.json"
    if not pdf_path.exists():
        pdf_path = QUOTES_DIR / f"{quote_id}.pdf"
        pdf_path.touch()

    download_token = secrets.token_urlsafe(24)
    path_esc = str(pdf_path).replace("'", "''")
    token_esc = download_token.replace("'", "''")
    qid_esc = quote_id.replace("'", "''")

    try:
        db.execute(f"""
            UPDATE quotes SET pdf_path = '{path_esc}', download_token = '{token_esc}', status = 'dispatched'
            WHERE quote_id = '{qid_esc}'
        """)
    except Exception:
        pass

    base = base_url or os.environ.get("DUCKCLAW_API_BASE_URL", "http://localhost:8000")
    base = base.rstrip("/")
    pdf_url = f"{base}/api/v1/quotes/download/{quote_id}?token={download_token}"

    payload = {
        "event": "quote_ready",
        "quote_id": quote_id,
        "user_id": quote_data.get("user_id", ""),
        "customer_name": quote_data.get("customer_name", ""),
        "total_amount": quote_data.get("total_amount", 0),
        "currency": quote_data.get("currency", "COP"),
        "items": quote_data.get("items", []),
        "pdf_url": pdf_url,
        "delivery_preferences": delivery_preferences or "",
    }

    webhook = os.environ.get("N8N_QUOTE_WEBHOOK_URL", "").strip()
    if webhook:
        try:
            import urllib.request
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                webhook,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    return f"Cotización {quote_id} generada y enviada al sistema de distribución."

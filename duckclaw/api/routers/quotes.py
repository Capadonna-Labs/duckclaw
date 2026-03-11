"""Router: descarga segura de cotizaciones (PDF). Spec: Motor_Cotizacion_Omnicanal."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/v1/quotes", tags=["quotes"])


def _get_db():
    from duckclaw import DuckClaw
    from duckclaw.gateway_db import get_gateway_db_path
    path = get_gateway_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return DuckClaw(path)


@router.get("/download/{quote_id}", summary="Descarga PDF de cotización (token de un solo uso)")
async def download_quote(quote_id: str, request: Request, token: str = ""):
    """
    Descarga el PDF de una cotización. Requiere token en query (?token=xxx).
    Token de un solo uso: se invalida tras la descarga.
    Auditoría: se registra IP y timestamp.
    """
    if not quote_id or not token:
        raise HTTPException(status_code=400, detail="quote_id y token son requeridos")

    db = _get_db()
    qid_esc = quote_id.replace("'", "''")
    token_esc = token.replace("'", "''")

    try:
        r = db.query(
            f"SELECT pdf_path, download_token FROM quotes WHERE quote_id = '{qid_esc}' LIMIT 1"
        )
        rows = json.loads(r) if isinstance(r, str) else (r or [])
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error consultando cotización")

    if not rows or not isinstance(rows[0], dict):
        raise HTTPException(status_code=404, detail="Cotización no encontrada")

    row = rows[0]
    stored_token = row.get("download_token") or ""
    pdf_path = row.get("pdf_path") or ""

    if stored_token != token:
        raise HTTPException(status_code=403, detail="Token inválido o ya utilizado")

    path = Path(pdf_path)
    if not path.is_file():
        # Fallback: JSON
        json_path = path.with_suffix(".json") if path.suffix == ".pdf" else path.parent / f"{quote_id}.json"
        if json_path.is_file():
            path = json_path
        else:
            raise HTTPException(status_code=404, detail="Archivo de cotización no encontrado")

    # Invalidar token (un solo uso)
    try:
        db.execute(f"UPDATE quotes SET download_token = NULL WHERE quote_id = '{qid_esc}'")
    except Exception:
        pass

    # Auditoría: log descarga
    client_ip = request.client.host if request.client else "unknown"
    logging.getLogger(__name__).info(
        "quote_downloaded quote_id=%s ip=%s", quote_id, client_ip
    )

    media_type = "application/pdf" if path.suffix.lower() == ".pdf" else "application/json"
    return FileResponse(path, media_type=media_type, filename=f"{quote_id}.pdf")

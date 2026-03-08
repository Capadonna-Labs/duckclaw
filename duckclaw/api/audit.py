"""AuditMiddleware — registro de peticiones y enmascaramiento Habeas Data."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

# Patrones para anonimización (Habeas Data)
_CARD_PATTERN = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")


def mask_sensitive_data(text: str) -> str:
    """
    Anonimiza tarjetas de crédito y emails antes de persistir en logs.
    Habeas Data: evita que datos sensibles lleguen a LangSmith.
    """
    if not text or not isinstance(text, str):
        return text
    out = _CARD_PATTERN.sub("[REDACTED]", text)
    out = _EMAIL_PATTERN.sub("[REDACTED]", out)
    return out


def _mask_dict(obj: Any) -> Any:
    """Recursivamente enmascara campos message y payload en dicts."""
    if obj is None:
        return None
    if isinstance(obj, str):
        return mask_sensitive_data(obj)
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            key_lower = (k or "").lower()
            if key_lower in ("message", "payload", "content", "text"):
                result[k] = mask_sensitive_data(str(v)) if v is not None else v
            else:
                result[k] = _mask_dict(v)
        return result
    if isinstance(obj, list):
        return [_mask_dict(x) for x in obj]
    return obj


async def audit_middleware(request: Any, call_next: Any):
    """
    Registra cada petición con user_id, worker_id, endpoint, timestamp.
    Envía a LangSmith si LANGCHAIN_TRACING_V2=true.
    Anonimiza message/payload antes de persistir (Habeas Data).
    """
    t0 = time.time()
    path = request.url.path or "/"
    method = getattr(request, "method", "GET") or "GET"

    # Extraer worker_id de path: /api/v1/agent/{worker_id}/... o /api/v1/homeostasis/{worker_id}/...
    worker_id = ""
    parts = path.strip("/").split("/")
    if "agent" in parts:
        idx = parts.index("agent")
        if idx + 1 < len(parts):
            worker_id = parts[idx + 1]
    elif "homeostasis" in parts:
        idx = parts.index("homeostasis")
        if idx + 1 < len(parts) and parts[idx + 1] != "status":
            worker_id = parts[idx + 1]

    # user_id desde JWT (si existe)
    user_id = None
    try:
        from duckclaw.api.auth import get_user_id_from_request
        user_id = get_user_id_from_request(request)
    except Exception:
        pass

    response = await call_next(request)

    elapsed_ms = int((time.time() - t0) * 1000)
    audit_entry = {
        "user_id": user_id,
        "worker_id": worker_id or None,
        "endpoint": f"{method} {path}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_ms": elapsed_ms,
        "status_code": getattr(response, "status_code", None),
    }

    # Enviar a LangSmith si está habilitado (opcional, no falla si no disponible)
    if os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true":
        try:
            from langsmith import Client
            client = Client()
            run = client.create_run(
                name="gateway_audit",
                run_type="chain",
                inputs=_mask_dict({"audit": audit_entry}),
                extra={"audit": audit_entry},
            )
            client.update_run(run.id, outputs={"status": "ok"})
        except Exception:
            pass

    return response

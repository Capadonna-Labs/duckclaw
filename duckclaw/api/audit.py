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


def _get_source_ip(request: Any) -> Optional[str]:
    """Obtiene source_ip: X-Forwarded-For (Cloudflare) o request.client.host."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if getattr(request, "client", None) and hasattr(request.client, "host"):
        return request.client.host
    return None


def _get_source_type(auth_source: str) -> str:
    """
    Mapea auth_source a INTERNAL_TRUSTED o PUBLIC_EXTERNAL (Habeas Data).
    tailscale = INTERNAL_TRUSTED (VPS/n8n vía Mesh).
    jwt, public = PUBLIC_EXTERNAL (Angular, Cloudflare).
    """
    if auth_source == "tailscale":
        return "INTERNAL_TRUSTED"
    if auth_source in ("jwt", "public"):
        return "PUBLIC_EXTERNAL"
    return "UNKNOWN"


async def audit_middleware(request: Any, call_next: Any):
    """
    Registra cada petición con user_id, worker_id, endpoint, timestamp,
    source_ip y source_type (INTERNAL_TRUSTED / PUBLIC_EXTERNAL) para Habeas Data.
    Anonimiza message/payload antes de persistir.
    """
    t0 = time.time()
    path = request.url.path or "/"
    method = getattr(request, "method", "GET") or "GET"

    # source_ip y source_type (auth debe haber corrido antes; middleware order: auth -> rate_limit -> audit)
    source_ip = _get_source_ip(request)
    auth_source = getattr(request.state, "auth_source", "unknown")
    source_type = _get_source_type(auth_source)

    # Extraer tenant_id de path: /api/v1/t/{tenant_id}/...
    tenant_id = None
    parts = path.strip("/").split("/")
    if len(parts) >= 4 and parts[0] == "api" and parts[1] == "v1" and parts[2] == "t":
        tenant_id = parts[3]

    # Extraer worker_id de path: /api/v1/agent/{worker_id}/... o /api/v1/t/{tenant}/agent/{worker_id}/...
    worker_id = ""
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
        "tenant_id": tenant_id,
        "endpoint": f"{method} {path}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_ms": elapsed_ms,
        "status_code": getattr(response, "status_code", None),
        "source_ip": source_ip,
        "source_type": source_type,
    }

    # (Eliminado) Ya no se envían trazas de gateway_audit a LangSmith para mantener el panel limpio
    # y mostrar únicamente las interacciones internas del agente (LangGraph).

    return response

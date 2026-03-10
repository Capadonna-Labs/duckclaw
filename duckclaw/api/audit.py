"""AuditMiddleware — registro de peticiones y enmascaramiento Habeas Data."""

from __future__ import annotations

import os
import time
from typing import Any, Optional

_datamasker: Any = None


def _get_datamasker() -> Any:
    """Lazy init DataMasker for PII anonymization."""
    global _datamasker
    if _datamasker is None:
        try:
            from duckclaw.forge.sft.datamasker import DataMasker

            _datamasker = DataMasker()
        except ImportError:
            _datamasker = False
    return _datamasker


def _mask_dict(obj: Any) -> Any:
    """Recursivamente enmascara campos message y payload en dicts."""
    masker = _get_datamasker()
    mask_fn = masker.mask if masker else (lambda x: x)

    def _mask(val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, str):
            return mask_fn(val)
        if isinstance(val, dict):
            result = {}
            for k, v in val.items():
                key_lower = (k or "").lower()
                if key_lower in ("message", "payload", "content", "text"):
                    result[k] = mask_fn(str(v)) if v is not None else v
                else:
                    result[k] = _mask(v)
            return result
        if isinstance(val, list):
            return [_mask(x) for x in val]
        return val

    return _mask(obj)


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

    # (Eliminado) Ya no se envían trazas de gateway_audit a LangSmith para mantener el panel limpio
    # y mostrar únicamente las interacciones internas del agente (LangGraph).

    return response

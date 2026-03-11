"""Autenticación dual: X-Tailscale-Auth-Key (n8n) y JWT Bearer (Angular)."""

from __future__ import annotations

import os
from typing import Any, Optional

# Rutas públicas (sin auth)
PUBLIC_PATHS = frozenset({
    "/",
    "/health",
    "/api/v1/system/health",
    "/api/v1/system/db-path",  # debug: ruta DB en uso
    "/api/v1/agent/llm-config",  # debug: estado del LLM (sin secrets)
    "/api/v1/agent/clear-cache",  # debug: limpiar caché de grafos
    "/docs",
    "/redoc",
    "/openapi.json",
})


def _path_is_public(path: str) -> bool:
    p = path.rstrip("/") or "/"
    if p in PUBLIC_PATHS:
        return True
    # /docs/*, /redoc/*, /openapi.json
    if p.startswith("/docs") or p.startswith("/redoc") or p.startswith("/openapi"):
        return True
    return False


def verify_tailscale_key(request: Any) -> bool:
    """True si X-Tailscale-Auth-Key es válida."""
    auth_key = os.environ.get("DUCKCLAW_TAILSCALE_AUTH_KEY", "").strip()
    if not auth_key:
        return False
    header_key = request.headers.get("X-Tailscale-Auth-Key", "").strip()
    return header_key == auth_key


def verify_jwt(request: Any) -> Optional[dict]:
    """
    Valida Authorization: Bearer <token> como JWT.
    Retorna payload si válido, None si no hay token o es inválido.
    Requiere PyJWT (uv sync --extra serve).
    """
    secret = os.environ.get("DUCKCLAW_JWT_SECRET", "").strip()
    if not secret:
        return None
    auth = request.headers.get("Authorization", "").strip()
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        import jwt as pyjwt
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        return dict(payload) if isinstance(payload, dict) else None
    except ImportError:
        return None
    except Exception:
        return None


def get_user_id_from_request(request: Any) -> Optional[str]:
    """Extrae user_id del JWT si existe."""
    payload = verify_jwt(request)
    if not payload:
        return None
    return payload.get("sub") or payload.get("user_id") or payload.get("uid")


async def verify_token(request: Any) -> Optional[dict]:
    """
    Valida autenticación: Tailscale o JWT.
    Retorna dict con auth info si OK, None si no autenticado.
    Lanza HTTPException 401 si la ruta requiere auth y falla.
    """
    from fastapi import HTTPException

    path = request.url.path.rstrip("/") or "/"
    if _path_is_public(path):
        return {"public": True}

    if verify_tailscale_key(request):
        return {"source": "tailscale", "user_id": None}

    payload = verify_jwt(request)
    if payload:
        user_id = payload.get("sub") or payload.get("user_id") or payload.get("uid")
        return {"source": "jwt", "user_id": user_id, "payload": payload}

    # Requiere auth y no pasó
    raise HTTPException(status_code=401, detail="X-Tailscale-Auth-Key o Authorization: Bearer <JWT> requeridos")


async def auth_middleware(request: Any, call_next: Any):
    """
    Middleware que valida autenticación para rutas protegidas.
    Rutas públicas: /, /health, /api/v1/system/health, /docs, /redoc.
    Guarda request.state.auth_source para audit: "public" | "tailscale" | "jwt".
    """
    from starlette.responses import JSONResponse

    path = request.url.path.rstrip("/") or "/"
    if _path_is_public(path):
        request.state.auth_source = "public"
        return await call_next(request)

    if verify_tailscale_key(request):
        request.state.auth_source = "tailscale"
        return await call_next(request)

    if verify_jwt(request) is not None:
        request.state.auth_source = "jwt"
        return await call_next(request)

    return JSONResponse(
        status_code=401,
        content={"detail": "X-Tailscale-Auth-Key o Authorization: Bearer <JWT> requeridos"},
    )

"""
DuckClaw API Gateway — único punto de entrada para Angular y n8n.

Spec: specs/API_Gateway_(FastAPI)_para_DuckClaw.md

Uso:
  uvicorn duckclaw.api.gateway:app --host 0.0.0.0 --port 8000
  duckops serve --gateway --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path

# Load .env
def _load_dotenv() -> None:
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent.parent):
        env_file = base / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    if key:
                        os.environ.setdefault(key, value)
            except Exception:
                pass
            break

_load_dotenv()

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:
    raise ImportError(
        "Instala las dependencias del servidor:\n  uv sync --extra serve"
    ) from exc

from duckclaw.api.auth import auth_middleware
from duckclaw.api.audit import audit_middleware
from duckclaw.api.rate_limit import rate_limit_middleware
from duckclaw.api.routers import agents, homeostasis, system

app = FastAPI(
    title="DuckClaw API Gateway",
    description="API Gateway para agentes LangGraph, homeostasis y observabilidad.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
_cors_origins = os.environ.get("DUCKCLAW_CORS_ORIGINS", "").strip()
if _cors_origins:
    origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
else:
    origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware: audit first, then rate limit, then auth
app.middleware("http")(audit_middleware)
app.middleware("http")(rate_limit_middleware)
app.middleware("http")(auth_middleware)

# Routers
app.include_router(agents.router)
app.include_router(homeostasis.router)
app.include_router(system.router)


@app.get("/", summary="Info del gateway")
async def root():
    return {
        "service": "DuckClaw API Gateway",
        "version": "0.1.0",
        "endpoints": [
            "/api/v1/agent/{worker_id}/chat",
            "/api/v1/agent/{worker_id}/history",
            "/api/v1/homeostasis/status",
            "/api/v1/homeostasis/{worker_id}/action",
            "/api/v1/system/health",
            "/api/v1/system/logs",
        ],
        "docs": "/docs",
    }


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok", "service": "DuckClaw API Gateway"}


def run_gateway(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Arranca el servidor del gateway."""
    import uvicorn
    try:
        port = int(os.environ.get("DUCKCLAW_API_PORT", str(port)))
    except ValueError:
        pass
    print(f"DuckClaw API Gateway → http://{host}:{port}", flush=True)
    print(f"   Docs  → http://{host}:{port}/docs", flush=True)
    uvicorn.run(
        "duckclaw.api.gateway:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    import argparse
    try:
        default_port = int(os.environ.get("DUCKCLAW_API_PORT", "8000"))
    except ValueError:
        default_port = 8000
    parser = argparse.ArgumentParser(description="DuckClaw API Gateway")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--port", default=default_port, type=int, help=f"Port (default: {default_port})")
    parser.add_argument("--reload", action="store_true", help="Auto-reload (dev)")
    args = parser.parse_args()
    run_gateway(host=args.host, port=args.port, reload=args.reload)

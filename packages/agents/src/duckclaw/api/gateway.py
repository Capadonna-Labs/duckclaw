# duckclaw.api.gateway — alias para la app del API Gateway (services/api-gateway/main.py).
# Permite arrancar con: uvicorn duckclaw.api.gateway:app

from duckclaw.api import app  # noqa: F401

__all__ = ["app"]

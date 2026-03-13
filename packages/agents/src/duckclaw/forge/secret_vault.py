"""
SecretVaultManager — inyección de secretos en runtime, borrado seguro post-uso.

Spec: specs/Auditoria_Arquitectura_y_Mejoras_Prioridad_Alta.md

Uso futuro:
  - Integrar SOPS o HashiCorp Vault
  - forge inyecta secretos en memoria
  - del + gc.collect() tras skill que usa credencial
"""

from __future__ import annotations

import gc
import os
from typing import Callable, TypeVar

T = TypeVar("T")


def get_secret(key: str, default: str = "") -> str:
    """Obtiene secreto de env (placeholder; en prod usar SOPS/Vault)."""
    return os.environ.get(key, default)


def with_secret_cleanup(key: str, fn: Callable[[str], T]) -> T:
    """
    Ejecuta fn(secret) y borra el secreto de memoria tras el uso.
    """
    secret = get_secret(key)
    try:
        return fn(secret)
    finally:
        del secret
        gc.collect()

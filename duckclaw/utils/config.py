"""Centralized configuration helpers: .env loading, boolean parsing, display model resolution."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"true", "1", "yes", "y", "sí", "si"})


def load_dotenv() -> None:
    """Load ``.env`` into ``os.environ`` (first found wins, no python-dotenv dependency).

    Searches ``Path.cwd()`` then the project root (three levels up from this file).
    Supports ``#`` comments, ``KEY=VALUE``, double- and single-quoted values with
    escaped quotes inside.
    """
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent.parent):
        env_file = base / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1].replace('\\"', '"')
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1].replace("\\'", "'")
                    if key:
                        os.environ.setdefault(key, value)
            except Exception:
                logger.debug("Error reading .env at %s", env_file, exc_info=True)
            break


def parse_bool(value: Any) -> bool:
    """Parse a boolean from various truthy string representations.

    Recognizes: ``true``, ``1``, ``yes``, ``y``, ``sí``, ``si`` (case-insensitive).
    """
    return str(value).strip().lower() in _TRUTHY


def resolve_display_model(
    provider: str = "",
    model: str = "",
) -> str:
    """Build a human-readable ``provider:model`` string for display/logging."""
    provider = (provider or os.environ.get("DUCKCLAW_LLM_PROVIDER", "")).strip().lower()
    model = (model or os.environ.get("DUCKCLAW_LLM_MODEL", "")).strip()

    if provider == "mlx":
        mid = (os.environ.get("MLX_MODEL_ID") or os.environ.get("MLX_MODEL_PATH") or "").strip()
        if mid:
            return f"mlx:{mid.rstrip('/').rsplit('/', 1)[-1]}"
        return f"mlx:{model or 'local'}"
    if model:
        return f"{provider}:{model}"
    return provider or "none_llm"

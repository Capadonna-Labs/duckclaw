"""DuckClaw Python package facade over the native C++ extension."""

from pathlib import Path

import warnings

# Suprime warning de Pydantic V1 en Python 3.14+ (langchain/pydantic)
warnings.filterwarnings(
    "ignore",
    message=".*Pydantic V1.*Python 3.14.*",
    category=UserWarning,
)

__all__ = ["DuckClaw", "get_datalake_path"]


def get_datalake_path(subdir: str = "datalake") -> str:
    """Ruta a la carpeta datalake en la raíz del proyecto (fuera de notebooks)."""
    root = Path(__file__).resolve().parents[1]
    return str(root / subdir)


def __getattr__(name: str):
    if name == "DuckClaw":
        from ._duckclaw import DuckClaw
        return DuckClaw
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

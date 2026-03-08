"""DuckClaw core package — façade sobre la extensión C++ nativa."""

from pathlib import Path
import warnings

warnings.filterwarnings(
    "ignore",
    message=".*Pydantic V1.*Python 3.14.*",
    category=UserWarning,
)

__all__ = ["DuckClaw", "get_datalake_path"]


def get_datalake_path(subdir: str = "datalake") -> str:
    root = Path(__file__).resolve().parents[1]
    return str(root / subdir)


def __getattr__(name: str):
    if name == "DuckClaw":
        try:
            # Intentar desde la extensión nativa en core/
            from ._duckclaw import DuckClaw
            return DuckClaw
        except ImportError:
            # Fallback: usar duckclaw package (que también tiene el .so)
            from duckclaw._duckclaw import DuckClaw
            return DuckClaw
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

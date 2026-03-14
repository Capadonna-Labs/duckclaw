"""DuckClaw Python package facade over the native C++ extension."""

from pathlib import Path
import pkgutil

# Merge duckclaw namespace (core + shared + agents: integrations, utils, gateway_db, etc.)
# Exclude root duckclaw/ (monorepo dev layout) so duckclaw.forge comes from agents
_extended = pkgutil.extend_path(__path__, __name__)
__path__ = [p for p in _extended if "packages/core" in p or "packages/shared" in p or "packages/agents" in p]
# Agents uses finder, not path; add agents/duckclaw for gateway_db, etc.
_agents_duckclaw = Path(__file__).resolve().parents[3] / "agents" / "src" / "duckclaw"
if _agents_duckclaw.exists():
    __path__.append(str(_agents_duckclaw))

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

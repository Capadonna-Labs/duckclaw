"""
duckclaw.forge — único punto de instanciación de agentes LangGraph.

Toda la configuración de agentes se declara en YAML dentro de forge/templates/.
AgentAssembler lee el YAML y devuelve un LangGraph compilado listo para usar.

Spec: Agent Forge Refactor
"""

from pathlib import Path

from .assembler import AgentAssembler

# Rutas a templates built-in
FORGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = FORGE_DIR / "templates"
ENTRY_ROUTER_YAML = TEMPLATES_DIR / "entry_router.yaml"
GENERAL_YAML = TEMPLATES_DIR / "general.yaml"
RETAIL_YAML = TEMPLATES_DIR / "retail.yaml"

# Ruta a templates de workers (templates/workers/ en la raíz del proyecto)
_PROJECT_ROOT = FORGE_DIR.parent.parent
WORKERS_TEMPLATES_DIR = _PROJECT_ROOT / "templates" / "workers"

__all__ = [
    "AgentAssembler",
    "ENTRY_ROUTER_YAML",
    "GENERAL_YAML",
    "RETAIL_YAML",
    "WORKERS_TEMPLATES_DIR",
    "TEMPLATES_DIR",
]

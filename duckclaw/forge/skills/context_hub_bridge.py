"""
ContextHub Bridge — Ground Truth de APIs externas vía CLI Context Hub.

Spec: specs/Subagent Spawning & Context Hub.md (sección ContextHubBridge)
Requiere: binario/CLI `chub` disponible en PATH y, opcionalmente,
          CONTEXT_HUB_API_KEY / CONTEXT_HUB_BASE_URL en entorno.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Optional


def _chub_available() -> bool:
    """
    True si el binario `chub` está disponible en PATH.
    No valida credenciales; se limita a comprobar que el ejecutable existe.
    """
    path = os.environ.get("PATH", "")
    exes = ["chub.exe", "chub"] if os.name == "nt" else ["chub"]
    for directory in path.split(os.pathsep):
        directory = (directory or "").strip()
        if not directory:
            continue
        for exe in exes:
            candidate = os.path.join(directory, exe)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return True
    return False


def _context_hub_tool(config: Optional[dict] = None) -> Optional[Any]:
    """
    Crea un StructuredTool para consultar Context Hub.

    Entradas:
    - api_name: nombre lógico de la API (p. ej. "interactive-brokers", "stripe").
    - resource: recurso opcional, por defecto "docs" (p. ej. "openapi", "examples").

    Salida:
    - Texto estructurado (markdown/JSON) con documentación relevante.
    - Mensaje de advertencia si no hay documentación o el CLI falla.
    """
    if not _chub_available():
        return None

    cfg = config or {}
    if cfg.get("enabled") is False:
        return None

    from langchain_core.tools import StructuredTool

    def _fetch(api_name: str, resource: str = "docs") -> str:
        api_name = (api_name or "").strip()
        resource = (resource or "docs").strip() or "docs"
        if not api_name:
            return "Debes indicar api_name (por ejemplo: 'interactive-brokers', 'stripe')."
        base_cmd = [
            "chub",
            "get",
            f"{api_name}/{resource}",
            "--lang",
            "python",
        ]
        env = os.environ.copy()
        try:
            result = subprocess.run(
                base_cmd,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            out = (result.stdout or "").strip()
            return out or f"No se encontró documentación para {api_name}/{resource} en Context Hub."
        except subprocess.CalledProcessError as e:
            msg = (e.stderr or e.stdout or "").strip()
            if msg:
                return f"Documentación no encontrada o error en Context Hub para {api_name}/{resource}: {msg}"
            return f"Documentación no encontrada en Context Hub para {api_name}/{resource}. Procede con precaución."
        except FileNotFoundError:
            return "CLI `chub` no encontrado en PATH. Instala Context Hub CLI o ajusta tu entorno."
        except Exception as e:  # noqa: BLE001
            return f"Error inesperado al consultar Context Hub: {e}"

    return StructuredTool.from_function(
        _fetch,
        name="context_hub_bridge",
        description=(
            "Consulta documentación oficial/actualizada de una API externa usando Context Hub. "
            "Úsala ANTES de escribir código o hacer llamadas a APIs externas. "
            "Parámetros: api_name (p. ej. 'interactive-brokers', 'stripe'), "
            "resource opcional (p. ej. 'docs', 'openapi', 'examples')."
        ),
    )


def register_context_hub_skill(
    tools_list: list[Any],
    context_hub_config: Optional[dict] = None,
) -> None:
    """
    Registra la herramienta ContextHubBridge en la lista de tools.

    Llamar desde build_general_graph (tools_spec) o desde build_worker_graph
    cuando el manifest/tools incluya 'context_hub_bridge'.
    """
    if not context_hub_config:
        context_hub_config = {"enabled": True}
    try:
        tool = _context_hub_tool(context_hub_config)
        if tool:
            tools_list.append(tool)
    except Exception:
        # Falla en silencio para no tumbar el grafo si Context Hub no está disponible.
        return


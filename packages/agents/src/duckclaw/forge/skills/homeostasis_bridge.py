"""
Homeostasis Bridge — registra el skill HomeostasisManager en workers con homeostasis_config.

Spec: specs/Estandar_de_Agentes_Homeostaticos_(Active_Inference_Framework).md
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langchain_core.tools import StructuredTool


def register_homeostasis_skill(
    tools_list: List[Any],
    spec: Any,
    db: Any,
    tools_by_name: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Registra la herramienta homeostasis_check en la lista de tools.
    Llamar desde factory cuando el manifest tiene homeostasis_config.
    """
    config = getattr(spec, "homeostasis_config", None)
    if not config or not isinstance(config, dict):
        return
    try:
        from duckclaw.forge.homeostasis import BeliefRegistry, HomeostasisManager

        registry = BeliefRegistry.from_config(config)
        schema = spec.schema_name
        by_name = tools_by_name or {t.name: t for t in tools_list}

        manager = HomeostasisManager(db=db, schema=schema, registry=registry, tools_by_name=by_name)

        def homeostasis_check(belief_key: str, observed_value: float) -> str:
            """Compara un valor observado con la creencia. Devuelve Action_Plan (restore o maintain)."""
            plan = manager.check(belief_key, observed_value, auto_update=True, invoke_restoration=False)
            return json.dumps(plan, ensure_ascii=False)

        tool = StructuredTool.from_function(
            homeostasis_check,
            name="homeostasis_check",
            description=(
                "Compara un valor observado con las creencias del agente (homeostasis). "
                "Recibe belief_key (ej. presupuesto_mensual, test_coverage) y observed_value. "
                "Devuelve Action_Plan: restore si hay anomalía, maintain si está en equilibrio."
            ),
        )
        tools_list.append(tool)
    except Exception:
        pass

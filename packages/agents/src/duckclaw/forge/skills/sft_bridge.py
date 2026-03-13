"""
SFT Bridge — tool para generar dataset SFT desde trazas.

Spec: specs/Migracion_de_Pipeline_de_Entrenamiento_(GRPO_a_SFT_con_MLX).md
"""

from __future__ import annotations

from typing import Any, Optional


def _collect_sft_dataset_impl(
    input_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """Genera dataset SFT desde trazas con reward 1.0."""
    from duckclaw.forge.sft import collect_traces_to_sft

    records, stats = collect_traces_to_sft(
        input_path=input_path,
        output_path=output_path,
    )
    return (
        f"Generado {stats['total_output']} ejemplos en {stats['output_path']}. "
        f"Omitidos: {stats['skipped_sql']} por SQL inválido, "
        f"{stats['skipped_reward']} por reward bajo."
    )


def _collect_sft_dataset_tool(config: Optional[dict] = None) -> Optional[Any]:
    """
    Crea un StructuredTool para generar dataset SFT.
    config: sft_enabled (bool).
    """
    cfg = config or {}
    if cfg.get("sft_enabled") is False:
        return None

    from langchain_core.tools import StructuredTool

    return StructuredTool.from_function(
        _collect_sft_dataset_impl,
        name="collect_sft_dataset",
        description="Genera dataset SFT desde trazas con reward 1.0. Aplica DataMasker (anonimiza PII) y valida SQL con sqlglot. Argumentos opcionales: input_path, output_path.",
    )


def register_sft_skill(
    tools_list: list[Any],
    sft_config: Optional[dict] = None,
) -> None:
    """
    Registra la herramienta collect_sft_dataset en la lista.
    Llamar desde build_worker_graph o build_general_graph cuando el manifest tiene skills.sft.
    """
    if not sft_config:
        return
    try:
        tool = _collect_sft_dataset_tool(sft_config)
        if tool:
            tools_list.append(tool)
    except Exception:
        pass

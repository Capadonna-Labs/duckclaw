"""
Forge SFT — pipeline de Supervised Fine-Tuning para MLX.

Spec: specs/Migracion_de_Pipeline_de_Entrenamiento_(GRPO_a_SFT_con_MLX).md
"""

from duckclaw.forge.sft.collector import (
    DEFAULT_SFT_DATASET_PATH,
    collect_traces_to_sft,
)
from duckclaw.forge.sft.datamasker import DataMasker

__all__ = [
    "DataMasker",
    "collect_traces_to_sft",
    "DEFAULT_SFT_DATASET_PATH",
]

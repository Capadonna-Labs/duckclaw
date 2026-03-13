"""
ShadowInferenceRouter — comparación post Hot-Swap para detectar deriva semántica.

Spec: specs/Auditoria_Arquitectura_y_Mejoras_Prioridad_Alta.md

Comportamiento:
  - 48h tras Hot-Swap: enrutar al modelo nuevo + inferencia en background al anterior
  - Calcular similitud coseno entre embeddings de respuestas
  - Si divergencia > 15% → alerta n8n + rollback automático
"""

from __future__ import annotations

from typing import Any, Optional

_DIVERGENCE_THRESHOLD = 0.15  # 15%


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Similitud coseno entre dos vectores."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_divergence(active_response: str, shadow_response: str) -> float:
    """
    Divergencia entre respuestas (0 = idénticas, 1 = totalmente distintas).
    Placeholder: usa longitud y overlap de tokens; en prod usar embeddings.
    """
    if not active_response or not shadow_response:
        return 1.0
    a_tokens = set(active_response.lower().split())
    b_tokens = set(shadow_response.lower().split())
    if not a_tokens and not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens) / max(len(a_tokens | b_tokens), 1)
    return 1.0 - overlap


def should_rollback(divergence: float, threshold: float = _DIVERGENCE_THRESHOLD) -> bool:
    """True si la divergencia supera el umbral crítico."""
    return divergence > threshold

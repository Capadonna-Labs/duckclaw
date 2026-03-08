"""SurpriseCalculator — define qué constituye una anomalía en el dominio del agente."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class SurpriseResult:
    """Resultado del cálculo de sorpresa."""

    delta: float
    is_anomaly: bool
    target: float
    observed: float
    threshold: float


def compute_surprise(
    observed: float,
    target: float,
    threshold: float,
) -> SurpriseResult:
    """
    Calcula sorpresa: delta = |observed - target|.
    Anomalía si delta > threshold.

    Args:
        observed: Valor percibido del entorno.
        target: Valor esperado (creencia).
        threshold: Umbral de tolerancia.

    Returns:
        SurpriseResult con delta, is_anomaly, etc.
    """
    delta = abs(observed - target)
    is_anomaly = delta > threshold
    return SurpriseResult(
        delta=delta,
        is_anomaly=is_anomaly,
        target=target,
        observed=observed,
        threshold=threshold,
    )


class SurpriseCalculator:
    """Calcula sorpresa comparando percepción con creencias."""

    @staticmethod
    def compute(observed: float, target: float, threshold: float) -> SurpriseResult:
        """Alias para compute_surprise."""
        return compute_surprise(observed, target, threshold)

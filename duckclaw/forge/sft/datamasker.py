"""
DataMasker — anonimización de PII para datasets SFT.

Spec: specs/Migracion_de_Pipeline_de_Entrenamiento_(GRPO_a_SFT_con_MLX).md
"""

from __future__ import annotations

import re


class DataMasker:
    """Reemplaza datos sensibles (tarjetas, emails) por [MASKED]."""

    # Tarjetas: 16 dígitos con separadores opcionales (espacios, guiones)
    _CARD_PATTERN = re.compile(
        r"\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"
    )
    # Emails: patrón básico
    _EMAIL_PATTERN = re.compile(
        r"[\w.+-]+@[\w.-]+\.\w+"
    )

    def mask(self, text: str) -> str:
        """Aplica máscara a PII en el texto. Retorna copia con [MASKED]."""
        if not text or not isinstance(text, str):
            return text
        out = self._CARD_PATTERN.sub("[MASKED]", text)
        out = self._EMAIL_PATTERN.sub("[MASKED]", out)
        return out

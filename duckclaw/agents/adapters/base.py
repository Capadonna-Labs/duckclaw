"""Clase base para adapters de agentes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional


class BaseAgent(ABC):
    """Base para adapters: recibe mensaje e historial y devuelve respuesta."""

    @abstractmethod
    def invoke(self, message: str, history: Optional[List[dict]] = None) -> str:
        """Ejecuta el agente con el mensaje actual y opcional historial de mensajes.
        history: lista de {"role": "user"|"assistant", "content": str}.
        Retorna el texto de respuesta del asistente."""
        raise NotImplementedError

    def with_system_prompt(self, system_prompt: str) -> "BaseAgent":
        """Configura el system prompt para este adapter. Por defecto retorna self."""
        return self

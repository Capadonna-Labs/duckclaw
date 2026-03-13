"""BeliefRegistry — define qué variables definen el equilibrio del agente."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Belief:
    """Una creencia del agente."""

    key: str
    target: float
    threshold: float


@dataclass
class RestorationAction:
    """Acción de restauración cuando hay anomalía."""

    trigger: str
    skill: str
    message: str


def load_beliefs_from_config(config: Optional[Dict[str, Any]]) -> Tuple[List[Belief], Dict[str, RestorationAction]]:
    """
    Parsea homeostasis config (YAML) y devuelve beliefs y actions.

    Args:
        config: Dict con keys 'beliefs' y 'actions' (o None).

    Returns:
        (lista de Belief, mapeo trigger -> RestorationAction)
    """
    beliefs: List[Belief] = []
    actions: Dict[str, RestorationAction] = {}
    if not config or not isinstance(config, dict):
        return beliefs, actions

    for b in config.get("beliefs") or []:
        if isinstance(b, dict) and b.get("key"):
            try:
                target = float(b.get("target", 0))
                threshold = float(b.get("threshold", 0))
                beliefs.append(Belief(key=str(b["key"]).strip(), target=target, threshold=threshold))
            except (TypeError, ValueError):
                pass

    for a in config.get("actions") or []:
        if isinstance(a, dict) and a.get("trigger"):
            trigger = str(a["trigger"]).strip()
            skill = str(a.get("skill") or "").strip()
            message = str(a.get("message") or "").strip()
            actions[trigger] = RestorationAction(trigger=trigger, skill=skill, message=message)

    return beliefs, actions


class BeliefRegistry:
    """Registro de creencias por worker."""

    def __init__(self, beliefs: List[Belief], actions: Dict[str, RestorationAction]):
        self.beliefs = beliefs
        self.actions = actions

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]]) -> "BeliefRegistry":
        """Crea BeliefRegistry desde homeostasis config."""
        beliefs, actions = load_beliefs_from_config(config)
        return cls(beliefs=beliefs, actions=actions)

    def get_belief(self, key: str) -> Optional[Belief]:
        """Obtiene una creencia por key."""
        for b in self.beliefs:
            if b.key == key:
                return b
        return None

    def get_action_for_trigger(self, trigger: str) -> Optional[RestorationAction]:
        """Obtiene la acción de restauración para un trigger."""
        return self.actions.get(trigger)

    def trigger_for_belief(self, belief_key: str, is_drop: bool = True) -> str:
        """Genera nombre de trigger típico: belief_key + _drop o _breach."""
        suffix = "drop" if is_drop else "breach"
        return f"{belief_key}_{suffix}"

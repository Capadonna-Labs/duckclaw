"""HomeostasisManager — skill que recibe belief_key, observed_value y devuelve Action_Plan."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from duckclaw.forge.homeostasis.belief_registry import BeliefRegistry
from duckclaw.forge.homeostasis.surprise import compute_surprise


def _safe_ident(name: str) -> str:
    """Safe schema/table identifier."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name.strip())


def _safe_key(key: str) -> str:
    """Safe belief_key for SQL (alphanumeric + underscore)."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in key.strip())


class HomeostasisManager:
    """
    Gestiona homeostasis: compara observed_value con belief, calcula sorpresa,
    devuelve Action_Plan (restore o maintain).
    """

    def __init__(
        self,
        db: Any,
        schema: str,
        registry: BeliefRegistry,
        tools_by_name: Optional[Dict[str, Any]] = None,
    ):
        self.db = db
        self.schema = _safe_ident(schema)
        self.registry = registry
        self.tools_by_name = tools_by_name or {}

    def _get_or_create_belief_row(self, belief_key: str, target: float, threshold: float) -> None:
        """Asegura que existe una fila en agent_beliefs para la creencia."""
        key_safe = _safe_key(belief_key)
        try:
            r = self.db.query(
                f"SELECT 1 FROM {self.schema}.agent_beliefs WHERE belief_key = '{key_safe}' LIMIT 1"
            )
            rows = json.loads(r) if isinstance(r, str) else (r or [])
            exists = len(rows) > 0
        except Exception:
            exists = False
        if exists:
            try:
                self.db.execute(
                    f"UPDATE {self.schema}.agent_beliefs SET target_value = {target}, threshold = {threshold} "
                    f"WHERE belief_key = '{key_safe}'"
                )
            except Exception:
                pass
        else:
            try:
                self.db.execute(
                    f"INSERT INTO {self.schema}.agent_beliefs (belief_key, target_value, observed_value, threshold) "
                    f"VALUES ('{key_safe}', {target}, NULL, {threshold})"
                )
            except Exception:
                pass

    def _update_observed(self, belief_key: str, observed_value: float) -> None:
        """Actualiza observed_value y last_updated en agent_beliefs."""
        key_safe = _safe_key(belief_key)
        try:
            self.db.execute(
                f"UPDATE {self.schema}.agent_beliefs "
                f"SET observed_value = {observed_value}, last_updated = CURRENT_TIMESTAMP "
                f"WHERE belief_key = '{key_safe}'"
            )
        except Exception:
            pass

    def check(
        self,
        belief_key: str,
        observed_value: float,
        *,
        auto_update: bool = True,
        invoke_restoration: bool = False,
    ) -> Dict[str, Any]:
        """
        Compara observed_value con la creencia. Devuelve Action_Plan.

        Args:
            belief_key: Clave de la creencia.
            observed_value: Valor percibido.
            auto_update: Si True, actualiza agent_beliefs con observed_value.
            invoke_restoration: Si True y hay anomalía, invoca la skill de restauración.

        Returns:
            Action_Plan: {action: "restore"|"maintain", message, skill_to_invoke, delta, ...}
        """
        belief = self.registry.get_belief(belief_key)
        if not belief:
            return {
                "action": "unknown",
                "message": f"Creencia '{belief_key}' no definida en homeostasis.",
                "belief_key": belief_key,
            }

        result = compute_surprise(observed_value, belief.target, belief.threshold)

        if auto_update:
            self._get_or_create_belief_row(belief_key, belief.target, belief.threshold)
            self._update_observed(belief_key, observed_value)

        if result.is_anomaly:
            trigger = self.registry.trigger_for_belief(belief_key, is_drop=observed_value < belief.target)
            restoration = self.registry.get_action_for_trigger(trigger)
            if not restoration:
                restoration = self.registry.get_action_for_trigger(f"{belief_key}_breach")
            if not restoration:
                restoration = self.registry.get_action_for_trigger(f"{belief_key}_drop")

            skill_to_invoke = restoration.skill if restoration else ""
            message = restoration.message if restoration else f"Anomalía en {belief_key}: delta={result.delta:.4f}"

            if invoke_restoration and skill_to_invoke and skill_to_invoke in self.tools_by_name:
                try:
                    tool = self.tools_by_name[skill_to_invoke]
                    tool.invoke({})
                except Exception as e:
                    message += f" [Error al invocar {skill_to_invoke}: {e}]"

            return {
                "action": "restore",
                "message": message,
                "skill_to_invoke": skill_to_invoke,
                "belief_key": belief_key,
                "delta": result.delta,
                "observed": observed_value,
                "target": belief.target,
                "threshold": belief.threshold,
            }
        else:
            return {
                "action": "maintain",
                "message": f"Equilibrio mantenido en {belief_key}.",
                "belief_key": belief_key,
                "delta": result.delta,
                "observed": observed_value,
                "target": belief.target,
            }

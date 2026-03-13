"""
Notificación homeostasis: webhook a n8n para preguntar "¿Qué tarea hacer?".

Cuando termina una tarea o el timer dispara, envía POST a N8N_HOMEOSTASIS_ASK_TASK_WEBHOOK_URL.
Incluye objetivos sugeridos para priorizar (aumentar ventas, disminuir tiempo de respuesta, etc.).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

_DEFAULT_MESSAGE = "¿Qué tarea quieres que haga?"
_DEFAULT_OBJECTIVES = [
    "Aumentar ventas de cierta categoría",
    "Disminuir tiempo de respuesta",
    "Mejorar disponibilidad de stock",
    "Optimizar presupuesto o tasa de ahorro",
]


def _get_suggested_objectives() -> List[str]:
    """Lee objetivos sugeridos desde DUCKCLAW_HOMEOSTASIS_OBJECTIVES (JSON array) o usa defaults."""
    raw = (os.environ.get("DUCKCLAW_HOMEOSTASIS_OBJECTIVES") or "").strip()
    if not raw:
        return _DEFAULT_OBJECTIVES
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return _DEFAULT_OBJECTIVES


def notify_ask_task(
    worker_id: Optional[str] = None,
    session_id: str = "default",
    trigger: str = "task_complete",
    suggested_objectives: Optional[List[str]] = None,
) -> None:
    """
    Envía POST al webhook de n8n si N8N_HOMEOSTASIS_ASK_TASK_WEBHOOK_URL está definido.
    Incluye suggested_objectives para que el usuario priorice (ventas, tiempo de respuesta, etc.).
    Fire-and-forget (no bloquea). Logging en caso de error.
    """
    url = (os.environ.get("N8N_HOMEOSTASIS_ASK_TASK_WEBHOOK_URL") or "").strip()
    if not url:
        return

    objectives = suggested_objectives if suggested_objectives is not None else _get_suggested_objectives()
    payload = {
        "trigger": trigger,
        "message": _DEFAULT_MESSAGE,
        "worker_id": worker_id or "",
        "session_id": session_id,
        "suggested_objectives": objectives,
    }

    def _do_post() -> None:
        try:
            data = json.dumps(payload).encode("utf-8")
            req = Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "homeostasis notify_ask_task: webhook returned %s",
                        resp.status,
                    )
        except URLError as e:
            logger.warning(
                "homeostasis notify_ask_task: webhook failed: %s",
                getattr(e, "reason", str(e)),
            )
        except Exception as e:
            logger.warning(
                "homeostasis notify_ask_task: %s",
                e,
            )

    threading.Thread(target=_do_post, daemon=True).start()

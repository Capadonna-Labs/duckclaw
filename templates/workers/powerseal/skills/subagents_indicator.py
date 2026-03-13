"""Skill: subagents_indicator — Notificación SSE de tareas paralelas (PowerSeal).

Este skill no ejecuta la lógica de cotización ni envío; solo emite eventos
SSE vía el Gateway para que la interfaz Angular muestre la animación de
"Ejecutando 2 tareas en paralelo..." mientras el agente trabaja.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool


def get_tools(db: Any, schema_name: str, spec: Any = None) -> list:
    from duckclaw.forge.atoms.subagents import emit_subagents_started, emit_subagents_finished

    def subagents_start_quote_email(
        correlation_id: str,
        user_id: str = "",
    ) -> str:
        """
        Emite un evento subagents_started con dos tareas paralelas:
        - Cotizar productos (QuoteEngine)
        - Enviar resumen al socio (n8n / document_dispatcher)

        correlation_id debe coincidir con session_id/chat_id que usa Angular
        para abrir el SSE en /api/v1/agent/subagents/stream.
        """
        corr = (correlation_id or "").strip() or "default"
        uid = (user_id or "").strip() or None
        tasks = [
            {
                "task_id": "quote-1",
                "label": "Cotizar productos",
                "status": "running",
            },
            {
                "task_id": "email-1",
                "label": "Enviar resumen al socio",
                "status": "running",
            },
        ]
        emit_subagents_started(corr, tasks, user_id=uid, worker_id="powerseal")
        return "Indicador de tareas paralelas activado."

    def subagents_finish_parallel_tasks(
        correlation_id: str,
        user_id: str = "",
    ) -> str:
        """
        Emite un evento subagents_finished para cerrar el indicador
        de tareas paralelas en Angular.
        """
        corr = (correlation_id or "").strip() or "default"
        uid = (user_id or "").strip() or None
        emit_subagents_finished(corr, user_id=uid, worker_id="powerseal")
        return "Indicador de tareas paralelas finalizado."

    return [
        StructuredTool.from_function(
            subagents_start_quote_email,
            name="subagents_start_quote_email",
            description=(
                "Notifica al frontend que se están ejecutando 2 tareas en paralelo "
                "(cotización y envío de resumen). Úsalo al inicio de un flujo de "
                "cotización compleja. Parámetros: correlation_id (session_id/chat_id), "
                "user_id opcional."
            ),
        ),
        StructuredTool.from_function(
            subagents_finish_parallel_tasks,
            name="subagents_finish_parallel_tasks",
            description=(
                "Notifica al frontend que las tareas paralelas han terminado. "
                "Parámetros: correlation_id (session_id/chat_id), user_id opcional."
            ),
        ),
    ]


"""
Subagent Spawning primitives (LangGraph Send API).

Spec: specs/Subagent Spawning & Context Hub.md

Este módulo implementa el nodo SubAgentSpawner que retorna una lista de objetos
Send(subgraph_name, payload), de modo que LangGraph gestione el paralelismo,
reintentos y persistencia en el Checkpointer de forma nativa.
Además emite eventos SSE (subagents_started / subagents_finished) vía POST al
Gateway para que Angular (ParallelTaskIndicatorComponent) muestre el progreso.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

_LOG = logging.getLogger(__name__)
_GATEWAY_URL_ENV = "DUCKCLAW_GATEWAY_URL"
_DEFAULT_GATEWAY_URL = "http://127.0.0.1:8000"

try:
    # LangGraph v0.2+ recomienda importar Send desde langgraph.types
    from langgraph.types import Send
except ImportError:  # pragma: no cover - fallback para versiones anteriores
    try:
        from langgraph.graph import Send  # type: ignore[assignment]
    except ImportError:  # pragma: no cover
        Send = Any  # type: ignore[assignment]


@dataclass
class SubTask:
    """
    Representa una subtarea a ejecutar por un subgrafo.

    Campos mínimos:
    - task_id: identificador estable de la tarea (ej. "quote-1", "email-1").
    - description: descripción legible de la tarea.
    - route: nombre lógico del subgrafo (ej. "quote_subgraph", "email_subgraph").
    - payload: diccionario con el estado inicial que recibirá el subgrafo.
    """

    task_id: str
    description: str
    route: str
    payload: Dict[str, Any]


def build_subtasks_from_todos(state: Dict[str, Any]) -> List[SubTask]:
    """
    Convierte la lista de `todos` del estado en SubTask con rutas de subgrafo.

    Convención:
    - task_id que empieza por "quote-" -> route = "quote_subgraph"
    - task_id que empieza por "email-" -> route = "email_subgraph"
    - caso genérico -> route = "worker_subgraph"
    """
    subtasks: List[SubTask] = []
    todos = state.get("todos") or []
    correlation_id = state.get("correlation_id")
    user = state.get("user")

    for todo in todos:
        task_id = str(todo.get("task_id") or "").strip()
        description = str(todo.get("description") or "").strip()
        if not task_id:
            continue

        if task_id.startswith("quote-"):
            route = "quote_subgraph"
        elif task_id.startswith("email-"):
            route = "email_subgraph"
        else:
            route = "worker_subgraph"

        payload: Dict[str, Any] = {
            "task_id": task_id,
            "description": description,
        }
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        if user is not None:
            payload["user"] = user

        # Pasar todo el objeto todo completo como contexto adicional
        payload["todo"] = todo

        subtasks.append(SubTask(task_id=task_id, description=description, route=route, payload=payload))

    return subtasks


def _gateway_base_url() -> str:
    return (os.environ.get(_GATEWAY_URL_ENV) or _DEFAULT_GATEWAY_URL).rstrip("/")


def _emit_subagent_event_sync(
    event: str,
    correlation_id: str,
    tasks: Optional[List[Dict[str, Any]]] = None,
    user_id: Optional[str] = None,
    worker_id: Optional[str] = None,
) -> None:
    """
    Publica un evento de subagentes al Gateway (POST /api/v1/agent/subagents/event).
    Síncrono para poder llamarse desde nodos de grafo que se ejecutan en sync.
    """
    payload: Dict[str, Any] = {
        "event": event,
        "correlation_id": correlation_id,
    }
    if user_id is not None:
        payload["user_id"] = user_id
    if worker_id is not None:
        payload["worker_id"] = worker_id
    if tasks is not None:
        payload["tasks"] = tasks
        payload["total_parallel_tasks"] = len(tasks)
    try:
        import requests
        url = f"{_gateway_base_url()}/api/v1/agent/subagents/event"
        resp = requests.post(url, json=payload, timeout=2)
        if resp.status_code != 200:
            _LOG.debug("subagent event POST %s -> %s", url, resp.status_code)
    except Exception as e:
        _LOG.debug("subagent event POST failed: %s", e)


def emit_subagents_started(
    correlation_id: str,
    tasks: List[Dict[str, Any]],
    user_id: Optional[str] = None,
    worker_id: Optional[str] = None,
) -> None:
    """
    Emite evento subagents_started para Angular (ParallelTaskIndicator).
    Cada ítem de tasks debe tener: task_id, label, status (p. ej. "running").
    """
    task_payloads = [
        {
            "task_id": t.get("task_id", ""),
            "label": t.get("label", t.get("description", "")),
            "status": t.get("status", "running"),
        }
        for t in tasks
    ]
    _emit_subagent_event_sync(
        "subagents_started",
        correlation_id,
        tasks=task_payloads,
        user_id=user_id,
        worker_id=worker_id,
    )


def emit_subagents_finished(
    correlation_id: str,
    user_id: Optional[str] = None,
    worker_id: Optional[str] = None,
) -> None:
    """Emite evento subagents_finished para que Angular cierre el indicador."""
    _emit_subagent_event_sync(
        "subagents_finished",
        correlation_id,
        tasks=[],
        user_id=user_id,
        worker_id=worker_id,
    )


def subagent_spawner_node(state: Dict[str, Any]) -> List[Any]:
    """
    Nodo SubAgentSpawner para LangGraph.

    Entrada esperada en `state`:
    - "todos": lista de subtareas (dicts) con al menos task_id y description.
    - opcionalmente "correlation_id", "user", "worker_id".

    Salida:
    - Lista de objetos Send(subgraph_name, payload) que LangGraph ejecutará en paralelo.
    Además emite subagents_started vía Gateway para SSE (Angular).
    """
    subtasks = build_subtasks_from_todos(state)
    sends: List[Any] = []

    correlation_id = (state.get("correlation_id") or state.get("chat_id") or "").strip() or "default"
    user = state.get("user")
    user_id = str(user.get("id", "")) if isinstance(user, dict) else None
    worker_id = (state.get("worker_id") or "").strip() or None

    if subtasks:
        tasks_for_sse = [
            {"task_id": st.task_id, "label": st.description, "status": "running"}
            for st in subtasks
        ]
        emit_subagents_started(
            correlation_id,
            tasks_for_sse,
            user_id=user_id,
            worker_id=worker_id,
        )

    for st in subtasks:
        if Send is Any:  # Fallback cuando Send no está disponible
            continue
        sends.append(Send(st.route, st.payload))

    return sends


from __future__ import annotations

from typing import Annotated, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ManagerAgentState(TypedDict, total=False):
    """
    Estado tipado para el grafo Manager.

    Claves mínimas:
    - messages: historial de mensajes del grafo (opcional, para compatibilidad con LangGraph).
    - chat_id: identificador del chat / sesión (tenant_id en task_audit_log).
    - tenant_id: identificador lógico del tenant (para whitelist y aislamiento de workers).
    - assigned_worker_id: worker al que se delegó la tarea (finanz, support, etc.).
    - incoming: mensaje original del usuario.
    - history: historial condensado de conversación (lista de mensajes o turnos).
    - planned_task: instrucción detallada que se envía al worker.
    - plan_title: título semántico del plan (máx. ~5 palabras).
    - tasks: lista de subtareas / todos inferidos por el planner.
    - task_summary: resumen corto para /tasks y activity.
    - available_templates: workers disponibles para delegación en este chat.
    - reply: respuesta final al usuario.
    - _audit_done: bandera interna para evitar doble escritura en task_audit_log.
    """

    messages: Annotated[List[BaseMessage], add_messages]
    chat_id: str
    tenant_id: str
    user_id: str
    vault_db_path: str
    assigned_worker_id: Optional[str]

    incoming: str
    history: list

    planned_task: str
    plan_title: Optional[str]
    tasks: Optional[List[str]]
    task_summary: Optional[str]

    available_templates: List[str]
    reply: str
    _audit_done: bool


"""
RunnableConfig para LangChain / LangGraph con nombres de run y metadata alineados a Observability 2.1.

- ``run_name``: solo el **worker_key** (ej. ``TheMindCrupier``, ``finanz``, ``manager``) para la columna Name en LangSmith.
  El tenant va en tags/metadata, no en el nombre.
- Tags sin PII: ``tenant:``, ``worker:``, ``env:``.
- Metadata: modelo, commit de despliegue, ids técnicos (Habeas Data: evitar datos sensibles en tags).
"""

from __future__ import annotations

import datetime
import os
from typing import Any, Mapping, Optional


def run_name_for_langsmith(worker_key: str) -> str:
    """
    Nombre visible en la columna **Name** de LangSmith.
    El orquestador se muestra como ``Manager``; el resto usa el id del template tal cual.
    """
    w = (worker_key or "").strip() or "unknown"
    if w.lower() == "manager":
        return "Manager"
    return w


def create_completed_langsmith_run(
    client: Any,
    *,
    name: str,
    run_type: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    tags: Optional[list[str]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """
    ``Client.create_run`` sin ``end_time`` deja el run en estado *running* en LangSmith (spinner infinito).
    Este helper fija ``start_time`` y ``end_time`` en el mismo instante para runs one-shot (auditoría).
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    kw: dict[str, Any] = {
        "name": name,
        "run_type": run_type,
        "inputs": inputs,
        "outputs": outputs,
        "start_time": now,
        "end_time": now,
    }
    if tags:
        kw["tags"] = tags
    if extra:
        kw["extra"] = extra
    client.create_run(**kw)


def get_tracing_config(
    tenant_id: str,
    worker_key: str,
    chat_id: str = "unknown",
    *,
    base: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Genera la configuración de RunnableConfig para LangChain/LangGraph.
    Alineado con Observability 2.1 y cumplimiento de Habeas Data.

    Evitar PII en tags: solo IDs y metadatos técnicos (tenant_id/chat_id van en
    metadata; los tags usan prefijos tenant:/worker:/env:).

    Si ``base`` es el RunnableConfig del run padre, se fusiona para conservar
    callbacks/configurable y el enlace padre-hijo en LangSmith.
    """
    model_name = os.getenv("DUCKCLAW_LLM_MODEL", "unknown")
    env = os.getenv("DUCKCLAW_ENV", "dev")
    commit = os.getenv("COMMIT_HASH") or os.getenv("DUCKCLAW_COMMIT") or "local"

    tid = (tenant_id or "").strip() or "default"
    wk = (worker_key or "").strip() or "unknown"
    cid = (chat_id or "").strip() or "unknown"

    layer: dict[str, Any] = {
        # Columna Name en LangSmith: identificador del worker/template (sin prefijo tenant).
        "run_name": run_name_for_langsmith(wk),
        "tags": [
            f"tenant:{tid}",
            f"worker:{wk}",
            f"env:{env}",
        ],
        "metadata": {
            "tenant_id": tid,
            "chat_id": cid,
            "worker_template": wk,
            "model_version": model_name,
            "deployment_id": commit,
        },
    }

    if base is None:
        return layer

    merged: dict[str, Any] = dict(base)
    merged["run_name"] = layer["run_name"]
    prev_tags = merged.get("tags")
    if isinstance(prev_tags, (list, tuple)):
        merged["tags"] = list(dict.fromkeys([*list(prev_tags), *layer["tags"]]))
    else:
        merged["tags"] = list(layer["tags"])
    parent_meta = dict(merged.get("metadata") or {}) if isinstance(merged.get("metadata"), dict) else {}
    parent_meta.update(layer["metadata"])
    merged["metadata"] = parent_meta
    return merged

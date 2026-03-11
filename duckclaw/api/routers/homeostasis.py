"""Módulo de homeostasis: status y acciones HITL."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/homeostasis", tags=["homeostasis"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_WORKERS_DIR = _PROJECT_ROOT / "templates" / "workers"


def _get_db_path() -> str:
    from duckclaw.gateway_db import get_gateway_db_path
    return get_gateway_db_path()


def _get_db() -> Any:
    from duckclaw import DuckClaw
    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return DuckClaw(db_path)


def _workers_with_homeostasis() -> list[tuple[str, str, dict]]:
    """Lista (worker_id, schema_name, homeostasis_config) de workers con homeostasis."""
    result: list[tuple[str, str, dict]] = []
    if not _WORKERS_DIR.is_dir():
        return result
    for d in _WORKERS_DIR.iterdir():
        if not d.is_dir():
            continue
        worker_id = d.name
        manifest_path = d / "manifest.yaml"
        homeostasis_path = d / "homeostasis.yaml"
        config = None
        schema_name = worker_id.lower().replace("-", "_") + "_worker"
        if manifest_path.is_file():
            try:
                import yaml
                data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                schema_name = (data.get("schema_name") or data.get("schema") or schema_name).strip()
                config = data.get("homeostasis") or (data.get("homeostasis_config") if isinstance(data.get("homeostasis_config"), dict) else None)
            except Exception:
                pass
        if config is None and homeostasis_path.is_file():
            try:
                import yaml
                data = yaml.safe_load(homeostasis_path.read_text(encoding="utf-8")) or {}
                config = data.get("homeostasis") or data
            except Exception:
                pass
        if config and isinstance(config, dict) and config.get("beliefs"):
            result.append((worker_id, schema_name, config))
    return result


def _belief_status(delta: float, threshold: float) -> str:
    """green | amber | red según delta vs threshold."""
    if delta <= threshold:
        return "green"
    if delta <= threshold * 1.5:
        return "amber"
    return "red"


@router.get("/status", summary="Estado de homeostasis de todos los workers")
async def homeostasis_status():
    """
    Retorna el estado de salud de todos los workers activos con homeostasis.
    Response: [{ worker_id, status, beliefs: [...] }]
    """
    db = _get_db()
    workers = _workers_with_homeostasis()
    out = []
    for worker_id, schema_name, config in workers:
        beliefs_list = config.get("beliefs") or []
        beliefs_out = []
        status = "green"
        schema_safe = "".join(c if c.isalnum() or c == "_" else "_" for c in schema_name)
        try:
            r = db.query(
                f"SELECT belief_key, target_value, observed_value, threshold "
                f"FROM {schema_safe}.agent_beliefs"
            )
            rows = json.loads(r) if isinstance(r, str) else (r or [])
        except Exception:
            rows = []
        for row in rows or []:
            key = row.get("belief_key") or ""
            target = float(row.get("target_value") or 0)
            observed = row.get("observed_value")
            threshold_val = float(row.get("threshold") or 0)
            if observed is None:
                delta = 0.0
                s = "green"
            else:
                delta = abs(float(observed) - target)
                s = _belief_status(delta, threshold_val)
            if s == "red":
                status = "red"
            elif s == "amber" and status != "red":
                status = "amber"
            beliefs_out.append({
                "key": key,
                "target": target,
                "observed": observed,
                "threshold": threshold_val,
                "delta": delta,
                "status": s,
            })
        if not beliefs_out:
            for b in beliefs_list:
                if isinstance(b, dict):
                    beliefs_out.append({
                        "key": b.get("key", ""),
                        "target": b.get("target", 0),
                        "observed": None,
                        "threshold": b.get("threshold", 0),
                        "delta": 0,
                        "status": "green",
                    })
        out.append({"worker_id": worker_id, "status": status, "beliefs": beliefs_out})
    return out


class AskTaskRequest(BaseModel):
    """Payload opcional para POST /homeostasis/ask_task."""
    worker_id: Optional[str] = Field(None, description="ID del worker")
    session_id: str = Field("default", description="ID de sesión")
    suggested_objectives: Optional[list[str]] = Field(
        None,
        description="Objetivos a priorizar (ej. aumentar ventas, disminuir tiempo de respuesta, etc.)",
    )


@router.post("/ask_task", summary="Disparar pregunta '¿Qué tarea hacer?' (timer o manual)")
async def homeostasis_ask_task(payload: Optional[AskTaskRequest] = Body(default=None)):
    """
    Envía webhook a n8n para preguntar al usuario qué tarea hacer.
    Incluye objetivos sugeridos para priorizar (ventas, tiempo de respuesta, stock, etc.).
    """
    from duckclaw.forge.homeostasis.notify import notify_ask_task

    worker_id = payload.worker_id if payload else None
    session_id = (payload.session_id or "default") if payload else "default"
    objectives = payload.suggested_objectives if payload else None
    notify_ask_task(
        worker_id=worker_id,
        session_id=session_id,
        trigger="timer",
        suggested_objectives=objectives,
    )
    return {"ok": True, "trigger": "timer"}


class HomeostasisActionRequest(BaseModel):
    """Payload para POST /homeostasis/{worker_id}/action."""
    belief_key: str = Field(..., description="Clave de la creencia")
    observed_value: Optional[float] = Field(None, description="Valor observado (opcional, para forzar check)")
    action: Optional[str] = Field(None, description="Acción (restore, etc.)")


@router.post("/{worker_id}/action", summary="Ejecutar acción de restauración (HITL)")
async def homeostasis_action(worker_id: str, payload: HomeostasisActionRequest):
    """
    Ejecuta una acción de restauración manualmente (Human-in-the-Loop).
    Invoca HomeostasisManager.check(..., invoke_restoration=True).
    """
    workers = _workers_with_homeostasis()
    worker_map = {w[0]: (w[1], w[2]) for w in workers}
    if worker_id not in worker_map:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' sin homeostasis configurado")
    schema_name, config = worker_map[worker_id]
    from duckclaw.forge.homeostasis import BeliefRegistry, HomeostasisManager, load_beliefs_from_config
    beliefs, actions = load_beliefs_from_config(config)
    registry = BeliefRegistry(beliefs, actions)
    db = _get_db()
    mgr = HomeostasisManager(db=db, schema=schema_name, registry=registry, tools_by_name={})
    observed = payload.observed_value
    if observed is None:
        try:
            schema_safe = "".join(c if c.isalnum() or c == "_" else "_" for c in schema_name)
            key_safe = "".join(c if c.isalnum() or c == "_" else "_" for c in payload.belief_key.strip())
            r = db.query(
                f"SELECT observed_value FROM {schema_safe}.agent_beliefs "
                f"WHERE belief_key = '{key_safe}' LIMIT 1"
            )
            rows = json.loads(r) if isinstance(r, str) else (r or [])
            if rows and rows[0].get("observed_value") is not None:
                observed = float(rows[0]["observed_value"])
        except Exception:
            pass
    if observed is None:
        raise HTTPException(status_code=400, detail="observed_value requerido o creencia sin valor en DB")
    plan = mgr.check(payload.belief_key, observed, auto_update=True, invoke_restoration=True)
    return plan

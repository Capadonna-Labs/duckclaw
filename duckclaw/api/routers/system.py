"""Módulo de sistema: health y logs."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _get_db_path() -> str:
    from duckclaw.gateway_db import get_gateway_db_path
    return get_gateway_db_path()


@router.get("/db-path", summary="Ruta de la base DuckDB en uso (debug)")
async def get_db_path():
    """Retorna la ruta de la DB que usa el API Gateway (conversaciones + workers)."""
    return {"db_path": _get_db_path()}


@router.get("/health", summary="Estado de conectividad (Tailscale, DuckDB, MLX)")
async def system_health():
    """
    Verifica conectividad con Tailscale, DuckDB y MLX.
    Response: { tailscale: "ok"|"down", duckdb: "ok", mlx: "ok"|"down" }
    """
    result: dict[str, str] = {"tailscale": "down", "duckdb": "down", "mlx": "down"}

    # Tailscale
    if shutil.which("tailscale"):
        try:
            r = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0 and r.stdout:
                import json
                data = json.loads(r.stdout)
                self_obj = data.get("Self") or {}
                if self_obj.get("Online", True):
                    result["tailscale"] = "ok"
        except Exception:
            pass

    # DuckDB
    try:
        from duckclaw import DuckClaw
        db_path = _get_db_path()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        db = DuckClaw(db_path)
        db.query("SELECT 1")
        result["duckdb"] = "ok"
    except Exception:
        pass

    # MLX
    base_url = (
        os.environ.get("DUCKCLAW_LLM_BASE_URL") or
        os.environ.get("MLX_BASE_URL") or
        "http://127.0.0.1:8080"
    ).strip().rstrip("/")
    health_url = f"{base_url}/health" if "/v1" not in base_url else f"{base_url.replace('/v1', '')}/health"
    try:
        import urllib.request
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                result["mlx"] = "ok"
    except Exception:
        pass

    return result


@router.get("/logs", summary="Stream de logs de agentes (PM2)")
async def system_logs(name: str = "", lines: int = 100):
    """
    Stream de logs vía PM2. Si name vacío, usa todos los procesos DuckClaw.
    Retorna SSE con líneas de log.
    """
    if not shutil.which("pm2"):
        return {"detail": "PM2 no instalado", "logs": []}

    try:
        cmd = ["pm2", "logs", "--lines", str(min(lines, 500)), "--nostream", "--raw"]
        if name.strip():
            cmd.append(name.strip())
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        out = (r.stdout or "") + (r.stderr or "")
        log_lines = [ln.strip() for ln in out.splitlines() if ln.strip()][:200]
        return {"logs": log_lines}
    except Exception as e:
        return {"detail": str(e), "logs": []}


@router.get("/logs/stream", summary="Stream SSE de logs PM2")
async def system_logs_stream(name: str = ""):
    """
    Stream de logs en tiempo real vía PM2 (SSE).
    name: nombre del proceso PM2 (vacío = todos).
    """
    if not shutil.which("pm2"):
        async def empty_gen() -> AsyncGenerator[str, None]:
            yield "data: {\"error\": \"PM2 no instalado\"}\n\n"

        return StreamingResponse(
            empty_gen(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    async def log_generator() -> AsyncGenerator[str, None]:
        proc = None
        try:
            cmd = ["pm2", "logs", "--raw", "--lines", "0"]
            if name.strip():
                cmd.append(name.strip())
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            if proc.stdout:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").strip()
                    if text:
                        yield f"data: {text}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {e}\n\n"
        finally:
            if proc and proc.returncode is None:
                proc.terminate()

    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )

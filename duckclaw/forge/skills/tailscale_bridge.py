"""
Tailscale Bridge — conectividad y descubrimiento en la red Mesh.

Spec: specs/Arquitectura_de_Red_Distribuida_(Tailscale_Mesh).md
Requiere: tailscale instalado en el sistema (curl -fsSL https://tailscale.com/install.sh | sh)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Optional


def _tailscale_available() -> bool:
    """True si tailscale está instalado y en PATH."""
    return shutil.which("tailscale") is not None


def _run_tailscale_status() -> str:
    """Ejecuta tailscale status --json o tailscale status. Retorna salida como str."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    try:
        result = subprocess.run(
            ["tailscale", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


def _parse_status_output(raw: str) -> tuple[str, list[str]]:
    """
    Parsea la salida de tailscale status. Retorna (ConnectionStatus, lista de peers).
    ConnectionStatus: "Active" o "Down".
    Peers: ["100.64.0.2 (hostname)", ...]
    """
    if not raw or not raw.strip():
        return "Down", []

    # Intentar JSON primero
    try:
        data = json.loads(raw)
        peers: list[str] = []
        status = "Down"

        # Self: estado local
        self_obj = data.get("Self") or {}
        if isinstance(self_obj, dict):
            exit_node = self_obj.get("ExitNode") or False
            online = self_obj.get("Online", True)
            if online and not exit_node:
                status = "Active"

        # Peer: nodos conectados
        peer_map = data.get("Peer") or {}
        if isinstance(peer_map, dict):
            for _pid, peer in peer_map.items():
                if isinstance(peer, dict):
                    hostname = peer.get("HostName") or peer.get("ComputedName") or "unknown"
                    addrs = peer.get("TailscaleIPs") or peer.get("TailscaleIP") or []
                    if isinstance(addrs, str):
                        addrs = [addrs]
                    ip = addrs[0] if addrs else ""
                    if ip:
                        peers.append(f"{ip} ({hostname})")

        return status, peers
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: parsear salida de texto plano "tailscale status"
    lines = raw.strip().splitlines()
    peers = []
    status = "Down"
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Formato típico: "100.64.0.2   hostname    user@   -"
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("100."):
            ip = parts[0]
            hostname = parts[1] if len(parts) > 1 else "unknown"
            peers.append(f"{ip} ({hostname})")
            status = "Active"
        elif "connected" in line.lower() or "online" in line.lower():
            status = "Active"

    return status, peers


def _tailscale_status_impl() -> str:
    """Implementación interna del tool. Retorna ConnectionStatus y peers."""
    raw = _run_tailscale_status()
    status, peers = _parse_status_output(raw)
    if peers:
        peers_str = ", ".join(peers[:10])
        if len(peers) > 10:
            peers_str += f" (+{len(peers) - 10} más)"
        return f"ConnectionStatus: {status} | Peers: {peers_str}"
    if status == "Down":
        return f"ConnectionStatus: Down | Error: tailscale no responde o no está conectado"
    return f"ConnectionStatus: {status}"


def _tailscale_status_tool(config: Optional[dict] = None) -> Optional[Any]:
    """
    Crea un StructuredTool para verificar el estado de la Tailnet.
    config: tailscale_enabled, service_mapping (opcional).
    """
    if not _tailscale_available():
        return None
    cfg = config or {}
    if cfg.get("tailscale_enabled") is False:
        return None

    from langchain_core.tools import StructuredTool

    return StructuredTool.from_function(
        lambda: _tailscale_status_impl(),
        name="tailscale_status",
        description="Verifica el estado de la red Tailscale Mesh. Retorna ConnectionStatus (Active/Down) y lista de peers conectados. Usa para diagnosticar conectividad entre Mac Mini y VPS.",
    )


def register_tailscale_skill(
    tools_list: list[Any],
    tailscale_config: Optional[dict] = None,
) -> None:
    """
    Registra la herramienta tailscale_status en la lista.
    Llamar desde build_worker_graph o build_general_graph cuando el manifest tiene skills.tailscale.
    """
    if not tailscale_config:
        return
    try:
        tool = _tailscale_status_tool(tailscale_config)
        if tool:
            tools_list.append(tool)
    except Exception:
        pass

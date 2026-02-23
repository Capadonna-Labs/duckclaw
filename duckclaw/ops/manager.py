"""Orchestrates deployment via providers; resolves absolute paths for Python and command."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any, Optional


def _resolve_python() -> str:
    """Current interpreter absolute path (respects venv/uv)."""
    return os.path.abspath(sys.executable)


def _resolve_command(command: str, cwd: Optional[str] = None) -> str:
    """
    Resolve command to an absolute form when it looks like a script path.
    If command is a single path (no spaces or starts with / or .), resolve to absolute.
    Otherwise return as-is (e.g. "-m duckclaw.agents.telegram_bot" or "python script.py").
    """
    base = (cwd or os.getcwd()) if cwd else os.getcwd()
    cmd = command.strip()
    if not cmd:
        return cmd
    # If it's clearly a path (existing file or starts with . or /), resolve
    if cmd.startswith("/") or cmd.startswith("."):
        p = Path(cmd) if cmd.startswith("/") else Path(base) / cmd.lstrip("./")
        if p.exists():
            return str(p.resolve())
        return str(Path(cmd).resolve() if cmd.startswith("/") else (Path(base) / cmd.lstrip("./")).resolve())
    # If first token looks like a script path
    first = cmd.split(None, 1)[0] if cmd.split() else cmd
    if not first.startswith("-") and (first.endswith(".py") or "/" in first or "\\" in first):
        p = Path(first) if Path(first).is_absolute() else Path(base) / first
        if p.exists():
            rest = cmd[len(first) :].strip()
            return f"{p.resolve()}{' ' + rest if rest else ''}"
    return command


def deploy(
    name: str,
    provider: str,
    command: str,
    schedule: Optional[str] = None,
    cwd: Optional[str] = None,
    windows_trigger: str = "onlogon",
    **kwargs: Any,
) -> str:
    """
    Deploy a long-running command under the given provider.
    Returns a human-readable status message.
    """
    python_path = _resolve_python()
    resolved_cmd = _resolve_command(command, cwd=cwd)
    effective_cwd = str(Path(cwd or os.getcwd()).resolve())

    prov = provider.strip().lower()
    if prov == "auto":
        system = platform.system()
        if system == "Windows":
            prov = "windows"
        elif system == "Linux":
            prov = "systemd"  # default for Linux; could add detection for systemd
        else:
            prov = "pm2"  # macOS and others use PM2 if available

    if prov == "cron":
        return _cron_not_implemented(name, resolved_cmd, schedule)

    if prov == "pm2":
        from duckclaw.ops.providers.pm2 import deploy_pm2
        return deploy_pm2(name=name, command=resolved_cmd, python_path=python_path, cwd=effective_cwd, **kwargs)
    if prov == "systemd":
        from duckclaw.ops.providers.systemd import deploy_systemd
        return deploy_systemd(name=name, command=resolved_cmd, python_path=python_path, cwd=effective_cwd, **kwargs)
    if prov == "windows":
        from duckclaw.ops.providers.windows import deploy_windows
        return deploy_windows(
            name=name,
            command=resolved_cmd,
            python_path=python_path,
            cwd=effective_cwd,
            schedule=schedule,
            trigger=windows_trigger,
            **kwargs,
        )

    return f"Unknown provider: {provider}. Use pm2, systemd, cron, windows, or auto."


def _cron_not_implemented(name: str, command: str, schedule: Optional[str]) -> str:
    return (
        "Provider 'cron' is not implemented yet. Use --provider pm2 (or systemd on Linux) for now. "
        f"(name={name!r}, command={command!r}, schedule={schedule!r})"
    )

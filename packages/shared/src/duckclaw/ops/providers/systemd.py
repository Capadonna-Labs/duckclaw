"""Systemd provider: generate .service file content; warn about sudo for /etc/systemd/system/."""

from __future__ import annotations

import getpass
from typing import Any, Optional, Tuple


def get_systemd_unit_content(
    name: str,
    command: str,
    python_path: str,
    cwd: str,
    **kwargs: Any,
) -> Tuple[str, str]:
    """
    Generate only the .service file content (no instructions).
    Returns (content, unit_filename) e.g. ("[Unit]...", "DuckClaw-Brain.service").
    """
    exec_start = f"{python_path} {command}" if command.strip().startswith("-") else f"{python_path} {command}"
    safe_name = name.replace(" ", "-").replace(".", "-")
    unit_name = f"{safe_name}.service"
    user = getpass.getuser()
    content = f"""[Unit]
Description=DuckClaw service: {name}
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={cwd}
ExecStart={exec_start}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    return content.strip(), unit_name


def deploy_systemd(
    name: str,
    command: str,
    python_path: str,
    cwd: str,
    **kwargs: Any,
) -> str:
    content, unit_name = get_systemd_unit_content(name, command=command, python_path=python_path, cwd=cwd, **kwargs)
    safe_name = name.replace(" ", "-").replace(".", "-")
    warning = (
        "You need sudo to install the unit file. Example:\n"
        f"  sudo cp /path/to/{unit_name} /etc/systemd/system/\n"
        "  sudo systemctl daemon-reload\n"
        f"  sudo systemctl enable --now {safe_name}\n"
    )
    return (
        f"Generated systemd unit content for '{name}'.\n"
        f"Save it to a file (e.g. {unit_name}) and then:\n{warning}\n"
        "--- Content ---\n"
        f"{content}\n"
        "--- End ---"
    )

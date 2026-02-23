"""Systemd provider: generate .service file content; warn about sudo for /etc/systemd/system/."""

from __future__ import annotations

import getpass
from typing import Any, Optional


def deploy_systemd(
    name: str,
    command: str,
    python_path: str,
    cwd: str,
    **kwargs: Any,
) -> str:
    # Generate unit file content. We use ExecStart with the current Python and the user's command.
    # command might be "-m duckclaw.agents.telegram_bot" or a path; run as: python_path + " " + command
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
        f"{content.strip()}\n"
        "--- End ---"
    )

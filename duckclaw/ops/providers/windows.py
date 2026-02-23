"""Windows provider: schtasks for ONLOGON or ONSTART."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Optional


def deploy_windows(
    name: str,
    command: str,
    python_path: str,
    cwd: str,
    schedule: Optional[str] = None,
    trigger: str = "onlogon",
    **kwargs: Any,
) -> str:
    if sys.platform != "win32":
        return "Error: Windows provider is only available on Windows."

    # /SC ONLOGON = at user logon; /SC ONSTART = at system startup
    sc = "ONLOGON" if trigger.lower() == "onlogon" else "ONSTART"
    # Run: python_path + " " + command from cwd
    exec_cmd = f'"{python_path}" {command}' if command.strip().startswith("-") else f'"{python_path}" {command}'
    task_name = name.replace(" ", "_")
    # schtasks /Create /TN "Name" /TR "command" /SC ONLOGON /RL HIGHEST optionally
    # /F = overwrite existing task
    args = [
        "schtasks",
        "/Create",
        "/F",
        "/TN", task_name,
        "/TR", exec_cmd,
        "/SC", sc,
        "/RL", "HIGHEST",
    ]
    if cwd:
        args.extend(["/WD", cwd])

    try:
        r = subprocess.run(args, capture_output=True, text=True, shell=False)
        if r.returncode != 0:
            return f"Error: schtasks failed. stderr: {r.stderr or r.stdout or 'unknown'}"
        return f"Windows: scheduled task '{task_name}' ({sc}). Use Task Scheduler or 'schtasks /Query /TN {task_name}' to manage."
    except Exception as e:
        return f"Error running schtasks: {e}"

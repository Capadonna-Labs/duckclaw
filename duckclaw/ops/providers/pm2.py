"""PM2 provider: detect pm2, run with current Python interpreter."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any, Optional


def is_pm2_available() -> bool:
    return shutil.which("pm2") is not None


def deploy_pm2(
    name: str,
    command: str,
    python_path: str,
    cwd: str,
    **kwargs: Any,
) -> str:
    if not is_pm2_available():
        return "Error: pm2 is not installed or not in PATH. Install it (e.g. npm install -g pm2) and retry."

    # PM2: script = Python executable, args after -- = command (e.g. -m module) so venv/uv is respected
    args = ["pm2", "start", python_path, "--name", name, "--cwd", cwd, "--"] + command.split()

    try:
        r = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
        if r.returncode != 0:
            return f"Error: pm2 start failed. stderr: {r.stderr or r.stdout or 'unknown'}"
        return f"pm2: started '{name}'. Use 'pm2 logs {name}' and 'pm2 save' to persist."
    except Exception as e:
        return f"Error running pm2: {e}"

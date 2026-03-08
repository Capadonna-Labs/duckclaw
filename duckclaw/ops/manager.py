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


def status(provider: str = "auto", name: Optional[str] = None) -> int:
    """
    Print a Rich summary of the active persistence service.
    Returns 0 on success, 1 if no provider found.
    """
    import shutil

    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich import box
        console = Console()
    except ImportError:
        console = None  # type: ignore[assignment]

    def _print(msg: str) -> None:
        if console:
            console.print(msg)
        else:
            print(msg)

    prov = provider.strip().lower()
    if prov == "auto":
        if shutil.which("pm2"):
            prov = "pm2"
        elif platform.system() == "Linux" and shutil.which("systemctl"):
            prov = "systemd"
        elif platform.system() == "Windows":
            prov = "windows"
        else:
            _print("[yellow]No se detectó ningún proveedor de persistencia (pm2, systemd, Windows).[/]")
            return 1

    # ── PM2 ──────────────────────────────────────────────────────────────────
    if prov == "pm2":
        import json
        import subprocess as sp

        try:
            result = sp.run(["pm2", "jlist"], capture_output=True, text=True, timeout=10)
            processes: list[dict] = json.loads(result.stdout or "[]")
        except Exception as e:
            _print(f"[red]Error consultando pm2: {e}[/]")
            return 1

        # Filter: if name provided → exact match; else → all processes
        if name:
            processes = [p for p in processes if p.get("name") == name]
        if not processes:
            label = f"'{name}'" if name else "ningún"
            _print(f"[yellow]pm2: {label} proceso encontrado.[/]")
            return 1

        if console:
            table = Table(
                box=box.ROUNDED,
                border_style="green",
                header_style="bold cyan",
                show_lines=False,
                title="[bold green]DuckClaw — Servicios de Persistencia (PM2)[/]",
                title_justify="left",
            )
            table.add_column("ID",     style="dim",         width=4)
            table.add_column("Nombre", style="bold white",  min_width=18)
            table.add_column("Estado", justify="center",    width=10)
            table.add_column("Uptime", justify="right",     width=12)
            table.add_column("Reinicios", justify="right",  width=10)
            table.add_column("CPU",    justify="right",     width=7)
            table.add_column("Memoria", justify="right",    width=10)
            table.add_column("Módulo / Script",             min_width=30)

            for p in processes:
                pm2_env = p.get("pm2_env", {})
                pid = str(p.get("pid", "—"))
                pname = p.get("name", "—")
                raw_status = pm2_env.get("status", "—")
                status_icon = {
                    "online":  "[green]● online[/]",
                    "stopped": "[dim]○ stopped[/]",
                    "errored": "[red]✗ errored[/]",
                    "launching": "[yellow]◎ launching[/]",
                }.get(raw_status, f"[dim]{raw_status}[/]")

                restarts = str(pm2_env.get("restart_time", "—"))

                # Uptime: pm2 stores created_at as ms epoch
                uptime_str = "—"
                created_at = pm2_env.get("created_at")
                if created_at and raw_status == "online":
                    import time
                    elapsed = int(time.time() * 1000) - int(created_at)
                    s = elapsed // 1000
                    if s < 60:
                        uptime_str = f"{s}s"
                    elif s < 3600:
                        uptime_str = f"{s // 60}m {s % 60}s"
                    else:
                        uptime_str = f"{s // 3600}h {(s % 3600) // 60}m"

                monit = p.get("monit", {})
                cpu = f"{monit.get('cpu', 0)}%"
                mem_bytes = monit.get("memory", 0)
                if mem_bytes >= 1024 ** 2:
                    mem = f"{mem_bytes / 1024 ** 2:.1f} MB"
                elif mem_bytes > 0:
                    mem = f"{mem_bytes / 1024:.0f} KB"
                else:
                    mem = "—"

                # Script / module
                script = pm2_env.get("pm_exec_path", "") or ""
                script_args = " ".join(pm2_env.get("args", []) or [])
                module_str = f"{script} {script_args}".strip()
                # Shorten path: keep last 2 segments
                from pathlib import Path as _P
                try:
                    parts = _P(script).parts
                    short = str(_P(*parts[-2:])) if len(parts) >= 2 else script
                    module_str = f"{short} {script_args}".strip()
                except Exception:
                    pass

                table.add_row(
                    str(p.get("pm_id", "—")),
                    pname,
                    status_icon,
                    uptime_str,
                    restarts,
                    cpu if raw_status == "online" else "—",
                    mem if raw_status == "online" else "—",
                    module_str,
                )

            console.print()
            console.print(table)

            # Footer: proveedor info
            pm2_bin = shutil.which("pm2") or "pm2"
            console.print(
                Panel(
                    f"[dim]Proveedor:[/] [bold]PM2[/]  [dim]·[/]  [dim]bin:[/] {pm2_bin}\n"
                    "[dim]Comandos:[/]  pm2 logs <nombre>  ·  pm2 restart <nombre>  ·  pm2 save",
                    border_style="dim",
                    padding=(0, 1),
                )
            )
            console.print()
        else:
            for p in processes:
                pm2_env = p.get("pm2_env", {})
                print(f"[{p.get('pm_id')}] {p.get('name')} — {pm2_env.get('status')} "
                      f"(restarts: {pm2_env.get('restart_time', 0)})")
        return 0

    # ── systemd ───────────────────────────────────────────────────────────────
    if prov == "systemd":
        import subprocess as sp
        unit = f"{name}.service" if name else "duckclaw*.service"
        try:
            r = sp.run(
                ["systemctl", "--user", "status", unit, "--no-pager"],
                capture_output=True, text=True, timeout=10,
            )
            output = (r.stdout or r.stderr or "").strip()
        except Exception as e:
            _print(f"[red]Error consultando systemd: {e}[/]")
            return 1
        if console:
            console.print(Panel(output, title="[bold green]systemd status[/]", border_style="green"))
        else:
            print(output)
        return 0

    # ── Windows ───────────────────────────────────────────────────────────────
    if prov == "windows":
        import subprocess as sp
        task = name or "DuckClaw*"
        try:
            r = sp.run(
                ["schtasks", "/query", "/fo", "LIST", "/tn", task],
                capture_output=True, text=True, timeout=10,
            )
            output = (r.stdout or r.stderr or "").strip()
        except Exception as e:
            _print(f"[red]Error consultando schtasks: {e}[/]")
            return 1
        if console:
            console.print(Panel(output, title="[bold green]Windows Task Scheduler[/]", border_style="green"))
        else:
            print(output)
        return 0

    _print(f"[red]Proveedor desconocido: {provider}[/]")
    return 1


def serve(
    host: str = "0.0.0.0",
    port: int = 8123,
    reload: bool = False,
    pm2: bool = False,
    name: str = "DuckClaw-API",
    cwd: Optional[str] = None,
    gateway: bool = False,
) -> int:
    """
    Start the DuckClaw LangGraph API server.
    If --pm2: deploy as a persistent PM2 service.
    Otherwise: run directly (blocking).
    """
    effective_cwd = str(Path(cwd or os.getcwd()).resolve())

    if pm2:
        from duckclaw.ops.providers.pm2 import is_pm2_available
        import shutil, json, subprocess as sp

        if not is_pm2_available():
            print("PM2 no está instalado. Instala con: npm install -g pm2")
            return 1

        python_path = _resolve_python()
        config_path = Path(effective_cwd) / "ecosystem.api.config.cjs"

        # Collect env vars for the API server
        env_vars: dict = {
            "PYTHONPATH": effective_cwd,
        }
        # Propagate LangSmith + LLM vars if set
        for key in (
            "LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT",
            "DUCKCLAW_LLM_PROVIDER", "DUCKCLAW_LLM_MODEL", "DUCKCLAW_LLM_BASE_URL",
            "DUCKCLAW_DB_PATH", "MLX_MODEL_ID", "MLX_MODEL_PATH",
        ):
            val = os.environ.get(key, "")
            if val:
                env_vars[key] = val

        module = "duckclaw.api.gateway" if gateway else "duckclaw.agents.graph_server"
        args_cmd = f"-m {module} --host {host} --port {port}"
        env_str = json.dumps(env_vars, indent=8)
        config_content = f"""/**
 * PM2 config for DuckClaw API server (generated by duckops serve --pm2).
 * Start:  pm2 start ecosystem.api.config.cjs
 * Docs:   http://localhost:{port}/docs
 * Health: http://localhost:{port}/health
 */
module.exports = {{
  apps: [
    {{
      name: "{name}",
      script: "{python_path}",
      args: "{args_cmd}",
      cwd: "{effective_cwd}",
      interpreter: "none",
      autorestart: true,
      watch: false,
      max_restarts: 10,
      env: {env_str},
    }},
  ],
}};
"""
        config_path.write_text(config_content, encoding="utf-8")
        print(f"✅  ecosystem.api.config.cjs generado: {config_path}", flush=True)

        # Start or restart
        existing = sp.run(["pm2", "id", name], capture_output=True, text=True)
        if existing.returncode == 0 and existing.stdout.strip() not in ("", "[]"):
            sp.run(["pm2", "restart", name, "--update-env"], check=False)
            print(f"🔄  PM2: {name} reiniciado.", flush=True)
        else:
            sp.run(["pm2", "start", str(config_path)], check=False)
            print(f"🚀  PM2: {name} iniciado.", flush=True)

        print(f"\n   API →  http://localhost:{port}", flush=True)
        print(f"   Docs → http://localhost:{port}/docs", flush=True)
        print(f"   Logs → pm2 logs {name}", flush=True)
        return 0

    # Run directly
    if gateway:
        from duckclaw.api.gateway import run_gateway
        run_gateway(host=host, port=port, reload=reload)
    else:
        from duckclaw.agents.graph_server import _run_server
        _run_server(host=host, port=port, reload=reload)
    return 0


def hire(
    worker_id: str,
    instance_name: Optional[str] = None,
    cwd: Optional[str] = None,
) -> int:
    """
    Deploy a Virtual Worker from template (Plug & Play).
    Validates template, generates .env.<instance_name>, injects into ecosystem.workers.config.cjs, starts PM2.
    """
    import json
    import subprocess as sp

    from duckclaw.ops.providers.pm2 import is_pm2_available
    from duckclaw.workers.factory import WorkerFactory
    from duckclaw.workers.manifest import load_manifest

    effective_cwd = str(Path(cwd or os.getcwd()).resolve())
    instance = (instance_name or worker_id).strip()
    if not instance:
        instance = worker_id

    # 1. Validate template
    try:
        spec = load_manifest(worker_id, Path(effective_cwd))
    except Exception as e:
        print(f"Error validando plantilla: {e}")
        return 1

    if not is_pm2_available():
        print("PM2 no está instalado. Instala con: npm install -g pm2")
        return 1

    python_path = _resolve_python()
    db_path = str(Path(effective_cwd) / "db" / f"workers_{instance}.duckdb")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # 2. Generate .env.<instance_name>
    env_file = Path(effective_cwd) / f".env.{instance}"
    env_lines = [
        f"DUCKCLAW_WORKER_ID={worker_id}",
        f"DUCKCLAW_WORKER_INSTANCE={instance}",
        f"DUCKCLAW_DB_PATH={db_path}",
        "PYTHONPATH=" + effective_cwd,
        f"LANGCHAIN_TAGS=worker_role:{worker_id},instance:{instance}",
    ]
    for key in (
        "TELEGRAM_BOT_TOKEN", "LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT",
        "DUCKCLAW_LLM_PROVIDER", "DUCKCLAW_LLM_MODEL", "DUCKCLAW_LLM_BASE_URL",
        "MLX_MODEL_ID", "MLX_MODEL_PATH",
    ):
        val = os.environ.get(key, "").strip()
        if val:
            env_lines.append(f"{key}={val}")
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    print(f"✅  {env_file}", flush=True)

    # 3. Generate ecosystem.workers.config.cjs (single app for this instance)
    config_path = Path(effective_cwd) / "ecosystem.workers.config.cjs"
    port = 8124 + (hash(instance) % 1000)
    config_content = f"""/**
 * PM2 config for DuckClaw Virtual Workers (generated by duckops hire).
 * Start:  pm2 start ecosystem.workers.config.cjs --only {instance}
 */
module.exports = {{
  apps: [
    {{
      name: "{instance}",
      script: "{python_path}",
      args: "-m duckclaw.workers.run_worker {worker_id} --instance {instance} --port {port}",
      cwd: "{effective_cwd}",
      interpreter: "none",
      autorestart: true,
      watch: false,
      env: {{
        DUCKCLAW_WORKER_ID: "{worker_id}",
        DUCKCLAW_WORKER_INSTANCE: "{instance}",
        DUCKCLAW_DB_PATH: "{db_path}",
        PYTHONPATH: "{effective_cwd}",
        WORKER_PORT: "{port}",
      }},
    }},
  ],
}};
"""
    config_path.write_text(config_content, encoding="utf-8")
    print(f"✅  {config_path}", flush=True)

    # 4. pm2 start --only <instance_name>
    existing = sp.run(["pm2", "id", instance], capture_output=True, text=True, cwd=effective_cwd)
    if existing.returncode == 0 and existing.stdout.strip() not in ("", "[]"):
        sp.run(["pm2", "restart", instance, "--update-env"], check=False, cwd=effective_cwd)
        print(f"🔄  PM2: {instance} reiniciado.", flush=True)
    else:
        sp.run(["pm2", "start", str(config_path), "--only", instance], check=False, cwd=effective_cwd)
        print(f"🚀  PM2: {instance} iniciado.", flush=True)
    print(f"   Worker → http://localhost:{port}/invoke  (POST message, history)", flush=True)
    print(f"   Logs   → pm2 logs {instance}", flush=True)
    return 0


def _cron_not_implemented(name: str, command: str, schedule: Optional[str]) -> str:
    return (
        "Provider 'cron' is not implemented yet. Use --provider pm2 (or systemd on Linux) for now. "
        f"(name={name!r}, command={command!r}, schedule={schedule!r})"
    )

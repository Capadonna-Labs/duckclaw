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


def _cron_not_implemented(name: str, command: str, schedule: Optional[str]) -> str:
    return (
        "Provider 'cron' is not implemented yet. Use --provider pm2 (or systemd on Linux) for now. "
        f"(name={name!r}, command={command!r}, schedule={schedule!r})"
    )

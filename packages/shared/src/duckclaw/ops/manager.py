"""Orchestrates deployment via providers; resolves absolute paths for Python and command."""

from __future__ import annotations

import json
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
    """
    base = (cwd or os.getcwd()) if cwd else os.getcwd()
    cmd = command.strip()
    if not cmd:
        return cmd
    if cmd.startswith("/") or cmd.startswith("."):
        p = Path(cmd) if cmd.startswith("/") else Path(base) / cmd.lstrip("./")
        if p.exists():
            return str(p.resolve())
        return str(Path(cmd).resolve() if cmd.startswith("/") else (Path(base) / cmd.lstrip("./")).resolve())
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
    """Deploy a long-running command under the given provider."""
    python_path = _resolve_python()
    resolved_cmd = _resolve_command(command, cwd=cwd)
    effective_cwd = str(Path(cwd or os.getcwd()).resolve())

    prov = provider.strip().lower()
    if prov == "auto":
        system = platform.system()
        if system == "Windows":
            prov = "windows"
        elif system == "Linux":
            prov = "systemd"
        else:
            prov = "pm2"

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
    """Print a Rich summary of the active persistence service."""
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

    if prov == "pm2":
        import json
        import subprocess as sp

        try:
            result = sp.run(["pm2", "jlist"], capture_output=True, text=True, timeout=10)
            processes: list[dict] = json.loads(result.stdout or "[]")
        except Exception as e:
            _print(f"[red]Error consultando pm2: {e}[/]")
            return 1

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
            table.add_column("ID", style="dim", width=4)
            table.add_column("Nombre", style="bold white", min_width=18)
            table.add_column("Estado", justify="center", width=10)
            table.add_column("Uptime", justify="right", width=12)
            table.add_column("Reinicios", justify="right", width=10)
            table.add_column("CPU", justify="right", width=7)
            table.add_column("Memoria", justify="right", width=10)
            table.add_column("Módulo / Script", min_width=30)

            for p in processes:
                pm2_env = p.get("pm2_env", {})
                raw_status = pm2_env.get("status", "—")
                status_icon = {
                    "online": "[green]● online[/]",
                    "stopped": "[dim]○ stopped[/]",
                    "errored": "[red]✗ errored[/]",
                    "launching": "[yellow]◎ launching[/]",
                }.get(raw_status, f"[dim]{raw_status}[/]")
                restarts = str(pm2_env.get("restart_time", "—"))
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
                mem = f"{mem_bytes / 1024 ** 2:.1f} MB" if mem_bytes >= 1024 ** 2 else ("—" if mem_bytes == 0 else f"{mem_bytes / 1024:.0f} KB")
                script = pm2_env.get("pm_exec_path", "") or ""
                script_args = " ".join(pm2_env.get("args", []) or [])
                module_str = f"{script} {script_args}".strip()
                try:
                    parts = Path(script).parts
                    short = str(Path(*parts[-2:])) if len(parts) >= 2 else script
                    module_str = f"{short} {script_args}".strip()
                except Exception:
                    pass

                table.add_row(
                    str(p.get("pm_id", "—")),
                    p.get("name", "—"),
                    status_icon,
                    uptime_str,
                    restarts,
                    cpu if raw_status == "online" else "—",
                    mem if raw_status == "online" else "—",
                    module_str,
                )

            console.print()
            console.print(table)
            pm2_bin = shutil.which("pm2") or "pm2"
            console.print(Panel(
                f"[dim]Proveedor:[/] [bold]PM2[/]  [dim]·[/]  [dim]bin:[/] {pm2_bin}\n"
                "[dim]Comandos:[/]  pm2 logs <nombre>  ·  pm2 restart <nombre>  ·  pm2 save",
                border_style="dim",
                padding=(0, 1),
            ))
            console.print()
        else:
            for p in processes:
                pm2_env = p.get("pm2_env", {})
                print(f"[{p.get('pm_id')}] {p.get('name')} — {pm2_env.get('status')} "
                      f"(restarts: {pm2_env.get('restart_time', 0)})")
        return 0

    if prov == "systemd":
        import subprocess as sp
        unit = f"{name}.service" if name else "duckclaw*.service"
        try:
            r = sp.run(["systemctl", "--user", "status", unit, "--no-pager"],
                       capture_output=True, text=True, timeout=10)
            output = (r.stdout or r.stderr or "").strip()
        except Exception as e:
            _print(f"[red]Error consultando systemd: {e}[/]")
            return 1
        if console:
            console.print(Panel(output, title="[bold green]systemd status[/]", border_style="green"))
        else:
            print(output)
        return 0

    if prov == "windows":
        import subprocess as sp
        task = name or "DuckClaw*"
        try:
            r = sp.run(["schtasks", "/query", "/fo", "LIST", "/tn", task],
                       capture_output=True, text=True, timeout=10)
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


API_GATEWAYS_PM2_JSON = "config/api_gateways_pm2.json"


def _api_gateways_json_path(effective_cwd: str) -> Path:
    return Path(effective_cwd) / API_GATEWAYS_PM2_JSON


def _load_merged_gateway_apps(effective_cwd: str) -> list[dict[str, Any]]:
    path = _api_gateways_json_path(effective_cwd)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        apps = data.get("apps", [])
        return apps if isinstance(apps, list) else []
    except Exception:
        return []


def _save_merged_gateway_apps(effective_cwd: str, apps: list[dict[str, Any]]) -> None:
    path = _api_gateways_json_path(effective_cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"apps": apps}, indent=2, ensure_ascii=False), encoding="utf-8")


def _env_dict_for_json(env: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in env.items():
        if v is None:
            continue
        out[str(k)] = str(v)
    return out


def _upsert_gateway_app(
    apps: list[dict[str, Any]],
    *,
    name: str,
    host: str,
    port: int,
    env_vars: dict[str, Any],
) -> list[dict[str, Any]]:
    payload = {
        "name": name,
        "host": host,
        "port": port,
        "env": _env_dict_for_json(env_vars),
    }
    for i, a in enumerate(apps):
        if isinstance(a, dict) and (a.get("name") or "").strip() == name:
            apps[i] = payload
            return apps
    apps.append(payload)
    return apps


def _compute_gateway_cluster_maps(
    apps: list[dict[str, Any]], effective_cwd: str
) -> tuple[dict[int, list[str]], dict[str, list[str]]]:
    """Índices puerto→nombres y ruta DuckDB resuelta→nombres (para detectar conflictos)."""
    root = Path(effective_cwd).resolve()
    by_port: dict[int, list[str]] = {}
    by_db: dict[str, list[str]] = {}
    for a in apps:
        if not isinstance(a, dict):
            continue
        n = (a.get("name") or "").strip()
        if not n:
            continue
        p = int(a.get("port") or 0)
        if p > 0:
            by_port.setdefault(p, []).append(n)
        env = a.get("env") or {}
        if not isinstance(env, dict):
            env = {}
        dbp = (env.get("DUCKCLAW_DB_PATH") or "").strip()
        if dbp:
            try:
                dp = Path(dbp)
                if not dp.is_absolute():
                    dp = root / dp
                db_key = str(dp.resolve())
            except Exception:
                db_key = dbp
            by_db.setdefault(db_key, []).append(n)
    return by_port, by_db


def analyze_gateway_cluster_conflicts(effective_cwd: str) -> dict[str, Any]:
    """
    Lee config/api_gateways_pm2.json y devuelve conflictos (puerto o DuckDB duplicados).
    Útil para el wizard o herramientas que necesitan datos estructurados.
    """
    apps = _load_merged_gateway_apps(effective_cwd)
    by_port, by_db = _compute_gateway_cluster_maps(apps, effective_cwd)
    dup_ports = {p: names for p, names in by_port.items() if len(names) > 1}
    dup_dbs = {k: names for k, names in by_db.items() if len(names) > 1}
    return {
        "cwd": effective_cwd,
        "apps": apps,
        "duplicate_ports": dup_ports,
        "duplicate_databases": dup_dbs,
        "has_conflicts": bool(dup_ports or dup_dbs),
    }


def save_gateway_cluster_config(effective_cwd: str, apps: list[dict[str, Any]]) -> None:
    """
    Persiste la lista fusionada en config/api_gateways_pm2.json y regenera
    config/ecosystem.api.config.cjs (mismo criterio que `duckops serve --pm2 --gateway`).
    """
    _warn_gateway_cluster_conflicts(apps, effective_cwd)
    _save_merged_gateway_apps(effective_cwd, apps)
    python_path = _resolve_python()
    config_path = Path(effective_cwd) / "config" / "ecosystem.api.config.cjs"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_content = _render_gateway_ecosystem_cjs(python_path, effective_cwd, apps)
    config_path.write_text(config_content, encoding="utf-8")
    print(
        f"✅  {API_GATEWAYS_PM2_JSON} + ecosystem.api.config.cjs ({len(apps)} gateway(s))",
        flush=True,
    )


def _warn_gateway_cluster_conflicts(apps: list[dict[str, Any]], effective_cwd: str) -> None:
    """
    Tras fusionar la lista de gateways: avisa si hay puerto o DuckDB duplicados.
    (errno 48 en bind, o lock DuckDB al compartir fichero entre procesos).
    """
    by_port, by_db = _compute_gateway_cluster_maps(apps, effective_cwd)
    for port, names in sorted(by_port.items()):
        if len(names) > 1:
            print(
                f"[red]⚠️  Puerto {port} repetido en: {', '.join(names)}. "
                "Solo uno puede escuchar; el resto falla con [Errno 48] address already in use. "
                "Configura un puerto distinto por gateway (p. ej. 8000, 8080, 8001) y `pm2 restart <nombre> --update-env`.[/]",
                flush=True,
            )
    for db_key, names in by_db.items():
        if len(names) > 1:
            print(
                f"[red]⚠️  Misma DuckDB compartida por: {', '.join(names)}[/]\n"
                f"    Archivo: {db_key}\n"
                "    DuckDB solo permite un proceso con escritura en ese fichero; verás locks o errores de concurrencia. "
                "Solución: un .duckdb por servicio, o deja un solo proceso usando esa BD (cierra el otro con `pm2 stop`).",
                flush=True,
            )


def _render_gateway_ecosystem_cjs(
    python_path: str,
    effective_cwd: str,
    apps: list[dict[str, Any]],
) -> str:
    """Genera ecosystem PM2 con varios gateways (mismo código, distinto nombre/puerto/env)."""
    lines = [
        "/**",
        " * PM2 — API Gateways DuckClaw (fusionado). Varios procesos en un solo archivo.",
        " * pm2 start config/ecosystem.api.config.cjs --only \"NombreGateway\"",
        " */",
        "module.exports = {",
        "  apps: [",
    ]
    for app in apps:
        if not isinstance(app, dict):
            continue
        name = (app.get("name") or "").strip()
        if not name:
            continue
        host = (app.get("host") or "0.0.0.0").strip()
        port = int(app.get("port") or 8000)
        env = app.get("env") or {}
        if not isinstance(env, dict):
            env = {}
        env = dict(env)
        env.setdefault("DUCKCLAW_PM2_PROCESS_NAME", name)
        env_str = json.dumps(env, indent=8, ensure_ascii=False)
        args_cmd = (
            f"-m uvicorn main:app --host {host} --port {port} --app-dir services/api-gateway"
        )
        lines.append("    {")
        lines.append(f"      name: {json.dumps(name)},")
        lines.append(f"      script: {json.dumps(python_path)},")
        lines.append(f"      args: {json.dumps(args_cmd)},")
        lines.append(f"      cwd: {json.dumps(effective_cwd)},")
        lines.append("      interpreter: \"none\",")
        lines.append("      autorestart: true,")
        lines.append("      watch: false,")
        lines.append("      max_restarts: 10,")
        lines.append(f"      env: {env_str},")
        lines.append("    },")
    lines.append("  ],")
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def pm2_delete_named_app(name: Optional[str]) -> bool:
    """
    Elimina un proceso PM2 por nombre si existe. Devuelve True si PM2 eliminó el proceso.
    """
    if not name or not str(name).strip():
        return False
    import shutil
    import subprocess as sp

    if shutil.which("pm2") is None:
        return False
    n = str(name).strip()
    r = sp.run(["pm2", "delete", n], capture_output=True, text=True, timeout=30)
    return r.returncode == 0


def serve(
    host: str = "0.0.0.0",
    port: int = 8123,
    reload: bool = False,
    pm2: bool = False,
    name: Optional[str] = None,
    cwd: Optional[str] = None,
    gateway: bool = False,
    delete_pm2_name: Optional[str] = None,
    gateway_db_path: Optional[str] = None,
) -> int:
    """
    Start the DuckClaw API server.
    gateway=True: services/api-gateway/main.py (uvicorn --app-dir services/api-gateway).
    Default name: DuckClaw-Gateway con gateway=True, DuckClaw-API si no.
    delete_pm2_name: opcional; elimina ese proceso PM2 antes de arrancar (sustitución explícita).
    gateway_db_path: si se indica, fija DUCKCLAW_DB_PATH solo para este proceso en el ecosystem
    (varios gateways pueden usar BDs distintas sin pisar el .env global).
    Con gateway+pm2 se fusionan varios gateways en config/api_gateways_pm2.json y ecosystem.api.config.cjs.
    """
    effective_name = name if name is not None else ("DuckClaw-Gateway" if gateway else "DuckClaw-API")
    effective_cwd = str(Path(cwd or os.getcwd()).resolve())

    if pm2:
        from duckclaw.ops.providers.pm2 import is_pm2_available
        import shutil
        import subprocess as sp

        if not is_pm2_available():
            print("PM2 no está instalado. Instala con: npm install -g pm2")
            return 1

        _env_file = Path(effective_cwd) / ".env"
        if _env_file.is_file():
            for _line in _env_file.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    if _k.strip():
                        os.environ.setdefault(_k.strip(), _v.strip().strip("'\"").strip())

        python_path = _resolve_python()
        config_path = Path(effective_cwd) / "config" / "ecosystem.api.config.cjs"
        graph_api_config_path = Path(effective_cwd) / "config" / "ecosystem.graph_api.config.cjs"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        env_vars: dict = {"PYTHONPATH": effective_cwd}
        for key in (
            "LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT",
            "DUCKCLAW_LLM_PROVIDER", "DUCKCLAW_LLM_MODEL", "DUCKCLAW_LLM_BASE_URL",
            "DUCKCLAW_DB_PATH", "MLX_MODEL_ID", "MLX_MODEL_PATH",
            "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "DUCKCLAW_REDIS_URL", "DUCKCLAW_WRITE_QUEUE_URL",
            "REDIS_URL", "DUCKCLAW_TAILSCALE_AUTH_KEY",
            "DUCKCLAW_SAVE_CONVERSATION_TRACES", "DUCKCLAW_CONVERSATION_TRACES_FORMAT",
        ):
            val = os.environ.get(key, "")
            if val:
                env_vars[key] = val
        if gateway and not env_vars.get("REDIS_URL") and env_vars.get("DUCKCLAW_REDIS_URL"):
            env_vars["REDIS_URL"] = env_vars["DUCKCLAW_REDIS_URL"]

        gwp = (gateway_db_path or "").strip()
        if gwp:
            _dbf = Path(gwp)
            if not _dbf.is_absolute():
                _dbf = Path(effective_cwd) / _dbf
            env_vars["DUCKCLAW_DB_PATH"] = str(_dbf.resolve())

        if gateway:
            env_vars["DUCKCLAW_PM2_PROCESS_NAME"] = effective_name
            # Varios API Gateways: fusionar en api_gateways_pm2.json + ecosystem (no borrar otros procesos).
            gw_port = int(port)
            apps = _load_merged_gateway_apps(effective_cwd)
            for a in apps:
                if not isinstance(a, dict):
                    continue
                other = (a.get("name") or "").strip()
                if other and other != effective_name and int(a.get("port") or 0) == gw_port:
                    print(
                        f"[yellow]⚠️  Otro gateway ({other}) ya usa el puerto {gw_port}. "
                        f"Cada instancia necesita un puerto distinto.[/]",
                        flush=True,
                    )
                    break
            apps = _upsert_gateway_app(
                apps,
                name=effective_name,
                host=host,
                port=gw_port,
                env_vars=dict(env_vars),
            )
            save_gateway_cluster_config(effective_cwd, apps)

            dn = (delete_pm2_name or "").strip()
            if dn and dn != effective_name and pm2_delete_named_app(dn):
                print(
                    f"🗑️  PM2: proceso eliminado ({dn}) antes de arrancar '{effective_name}'.",
                    flush=True,
                )

            _db_path = env_vars.get("DUCKCLAW_DB_PATH", "").strip()
            if _db_path:
                _db_file = Path(_db_path)
                if not _db_file.is_absolute():
                    _db_file = Path(effective_cwd) / _db_file
                _db_file = _db_file.resolve()
                _db_file.parent.mkdir(parents=True, exist_ok=True)
                if not _db_file.exists():
                    try:
                        _sys_path = sys.path.copy()
                        sys.path.insert(0, effective_cwd)
                        from duckclaw import DuckClaw
                        _db = DuckClaw(str(_db_file))
                        _db.execute("SELECT 1")
                        sys.path[:] = _sys_path
                        print(f"✅  BD creada: {_db_file}", flush=True)
                    except Exception as _e:
                        print(f"⚠️  No se pudo crear la BD en {_db_file}: {_e}", flush=True)

            existing = sp.run(["pm2", "id", effective_name], capture_output=True, text=True)
            if existing.returncode == 0 and existing.stdout.strip() not in ("", "[]"):
                sp.run(["pm2", "restart", effective_name, "--update-env"], check=False)
                print(f"🔄  PM2: {effective_name} reiniciado.", flush=True)
            else:
                sp.run(
                    ["pm2", "start", str(config_path), "--only", effective_name],
                    check=False,
                )
                print(f"🚀  PM2: {effective_name} iniciado (solo este proceso).", flush=True)

            print(f"\n   API →  http://localhost:{gw_port}", flush=True)
            print(f"   Docs → http://localhost:{gw_port}/docs", flush=True)
            print(f"   Logs → pm2 logs {effective_name}", flush=True)
            return 0

        args_cmd = f"-m uvicorn duckclaw.graphs.graph_server:app --host {host} --port {port}"

        env_str = json.dumps(env_vars, indent=8)
        config_content = f"""/**
 * PM2 — LangGraph HTTP (sin --gateway). No mezclar con ecosystem.api.config.cjs (API Gateways).
 * Start:  pm2 start config/ecosystem.graph_api.config.cjs
 */
module.exports = {{
  apps: [
    {{
      name: "{effective_name}",
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
        graph_api_config_path.write_text(config_content, encoding="utf-8")
        print(f"✅  config/ecosystem.graph_api.config.cjs generado: {graph_api_config_path}", flush=True)

        dn = (delete_pm2_name or "").strip()
        if dn and dn != effective_name and pm2_delete_named_app(dn):
            print(
                f"🗑️  PM2: proceso anterior eliminado ({dn}) → ahora '{effective_name}'.",
                flush=True,
            )

        _db_path = env_vars.get("DUCKCLAW_DB_PATH", "").strip()
        if _db_path:
            _db_file = Path(_db_path)
            if not _db_file.is_absolute():
                _db_file = Path(effective_cwd) / _db_file
            _db_file = _db_file.resolve()
            _db_file.parent.mkdir(parents=True, exist_ok=True)
            if not _db_file.exists():
                try:
                    _sys_path = sys.path.copy()
                    sys.path.insert(0, effective_cwd)
                    from duckclaw import DuckClaw
                    _db = DuckClaw(str(_db_file))
                    _db.execute("SELECT 1")
                    sys.path[:] = _sys_path
                    print(f"✅  BD creada: {_db_file}", flush=True)
                except Exception as _e:
                    print(f"⚠️  No se pudo crear la BD en {_db_file}: {_e}", flush=True)

        existing = sp.run(["pm2", "id", effective_name], capture_output=True, text=True)
        if existing.returncode == 0 and existing.stdout.strip() not in ("", "[]"):
            sp.run(["pm2", "restart", effective_name, "--update-env"], check=False)
            print(f"🔄  PM2: {effective_name} reiniciado.", flush=True)
        else:
            sp.run(["pm2", "start", str(graph_api_config_path)], check=False)
            print(f"🚀  PM2: {effective_name} iniciado.", flush=True)

        print(f"\n   API →  http://localhost:{port}", flush=True)
        print(f"   Docs → http://localhost:{port}/docs", flush=True)
        print(f"   Logs → pm2 logs {effective_name}", flush=True)
        return 0

    if gateway:
        import uvicorn
        app_dir = str(Path(effective_cwd) / "services" / "api-gateway")
        uvicorn.run("main:app", host=host, port=port, reload=reload, app_dir=app_dir, log_level="info")
    else:
        from duckclaw.graphs.graph_server import _run_server
        _run_server(host=host, port=port, reload=reload)
    return 0


def hire(
    worker_id: str,
    instance_name: Optional[str] = None,
    cwd: Optional[str] = None,
) -> int:
    """Deploy a Virtual Worker from template."""
    import json
    import subprocess as sp

    from duckclaw.ops.providers.pm2 import is_pm2_available
    from duckclaw.workers.factory import WorkerFactory
    from duckclaw.workers.manifest import load_manifest

    effective_cwd = str(Path(cwd or os.getcwd()).resolve())
    instance = (instance_name or worker_id).strip() or worker_id

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

    config_path = Path(effective_cwd) / "ecosystem.workers.config.cjs"
    port = 8124 + (hash(instance) % 1000)
    config_content = f"""/**
 * PM2 config for DuckClaw Virtual Workers (generated by duckops hire).
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

    existing = sp.run(["pm2", "id", instance], capture_output=True, text=True, cwd=effective_cwd)
    if existing.returncode == 0 and existing.stdout.strip() not in ("", "[]"):
        sp.run(["pm2", "restart", instance, "--update-env"], check=False, cwd=effective_cwd)
        print(f"🔄  PM2: {instance} reiniciado.", flush=True)
    else:
        sp.run(["pm2", "start", str(config_path), "--only", instance], check=False, cwd=effective_cwd)
        print(f"🚀  PM2: {instance} iniciado.", flush=True)
    print(f"   Worker → http://localhost:{port}/invoke", flush=True)
    print(f"   Logs   → pm2 logs {instance}", flush=True)
    return 0


def _cron_not_implemented(name: str, command: str, schedule: Optional[str]) -> str:
    return (
        "Provider 'cron' is not implemented yet. Use --provider pm2 (or systemd on Linux) for now. "
        f"(name={name!r}, command={command!r}, schedule={schedule!r})"
    )

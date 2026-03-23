#!/usr/bin/env python3
"""DuckClaw setup wizard: interactive install with Rich.

Spec: specs/FLUJO_VIDA_DATO_PIPELINE.md — gestiona DuckClaw-Gateway & DuckClaw-DB-Writer.
"""

from __future__ import annotations

import copy
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

# --write-systemd: generar unidad systemd sin importar Rich (salida temprana)
if "--write-systemd" in sys.argv:
    _repo = Path(__file__).resolve().parent.parent.parent.parent  # monorepo root
    sys.path.insert(0, str(_repo))
    for _base in (Path.cwd(), _repo):
        _env = _base / ".env"
        if _env.is_file():
            for _line in _env.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    if _k.strip():
                        os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))
            break
    from duckclaw.ops.providers.systemd import get_systemd_unit_content
    _py = os.path.abspath(sys.executable)
    _content, _fname = get_systemd_unit_content(
        name="DuckClaw-Brain", command="-m duckclaw.graphs.telegram_bot",
        python_path=_py, cwd=str(_repo),
    )
    _out = _repo / _fname
    _out.write_text(_content + "\n", encoding="utf-8")
    print(f"Unidad systemd escrita en: {_out}")
    print("Para instalar y activar:")
    print(f"  sudo cp {_out} /etc/systemd/system/")
    print("  sudo systemctl daemon-reload")
    print("  sudo systemctl enable --now DuckClaw-Brain")
    sys.exit(0)

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

NAV_NEXT = "next"
NAV_PREV = "prev"
NAV_QUIT = "quit"


def _prompt_with_nav(
    console: Console,
    prompt: str,
    *,
    choices: list[str] | None = None,
    default: str | None = None,
    password: bool = False,
) -> tuple[str | None, str | None]:
    """Prompt que acepta s/a/q como navegación. Devuelve (valor, nav) con nav in (next, prev, quit) o None."""
    raw = Prompt.ask(prompt, choices=choices, default=default, password=password)
    r = (raw or "").strip().lower()
    if r in ("s", "siguiente"):
        return None, NAV_NEXT
    if r in ("a", "anterior"):
        return None, NAV_PREV
    if r in ("q", "salir"):
        return None, NAV_QUIT
    return raw, None


def _confirm_with_nav(
    console: Console,
    prompt: str,
    *,
    default: bool = True,
) -> tuple[bool | None, str | None]:
    """Confirmación sí/no que acepta a=anterior y q=salir. Devuelve (respuesta, nav); si nav no es None, usar nav y ignorar respuesta."""
    default_str = "y" if default else "n"
    raw = Prompt.ask(f"{prompt} {escape('[y/n]')} [blue]({default_str})[/]")
    r = (raw or "").strip().lower()
    if r in ("a", "anterior"):
        return None, NAV_PREV
    if r in ("q", "salir"):
        return None, NAV_QUIT
    if r in ("s", "siguiente", "sí", "si", "y", "yes"):
        return True, None
    if r in ("n", "no"):
        return False, None
    if r == "":
        return default, None
    return default, None

CONFIG_KEYS = (
    "mode",
    "channel",
    "bot_mode",
    "llm_provider",
    "llm_model",
    "llm_base_url",
    "db_path",
    "save_grpo_traces",
    "send_to_langsmith",
    "save_conversation_traces",
    "conversation_traces_format",
    "gateway_pm2_name",
)
DEPLOY_PROVIDERS = ("auto", "pm2", "systemd", "windows", "cron")
DEPLOY_SERVICE_NAME = "DuckClaw-Brain"
GATEWAY_SERVICE_NAME = "DuckClaw-Gateway"  # spec FLUJO_VIDA_DATO: services/api-gateway
DB_WRITER_SERVICE_NAME = "DuckClaw-DB-Writer"  # spec FLUJO_VIDA_DATO: services/db-writer
INFERENCE_SERVICE_NAME = "DuckClaw-Inference"
# Orden: IoTCoreLabs, OpenAI, Anthropic, DeepSeek, MLX (principales); luego Ollama y none_llm
LLM_PROVIDERS = ("iotcorelabs", "openai", "anthropic", "deepseek", "huggingface", "mlx", "ollama", "none_llm")
TELEGRAM_TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
API_VALIDATION_TIMEOUT = 8

# Bienvenida → Canal → Modo del bot → Proveedor → … (provider/validate_provider/grpo_traces se saltan si bot_mode != "langgraph")
SECTION_IDS = (
    "welcome",
    "channel",
    "bot_mode",
    "provider",
    "mode",
    "deps",
    "token",
    "db_path",
    "grpo_traces",
    "conversation_traces",
    "validate_provider",
    "summary",
    "save_launch",
)


def _config_path() -> Path:
    return Path.home() / ".config" / "duckclaw" / "wizard_config.json"


def _load_dotenv() -> None:
    """Carga .env en os.environ si existe (busca en cwd y en la raíz del monorepo)."""
    _script_dir = Path(__file__).resolve().parent
    _repo_root = _script_dir.parent  # scripts/ -> repo root
    for base in (Path.cwd(), _repo_root, _script_dir.parent):
        env_file = base / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1].replace('\\"', '"')
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1].replace("\\'", "'")
                        if key:
                            os.environ.setdefault(key, value)
            except Exception:
                pass
            break


def _valid_db_path(db_path: Any) -> bool:
    """True si parece una ruta de DB válida (evita valores corruptos tipo descripciones de tools)."""
    if not db_path or not isinstance(db_path, str):
        return False
    s = db_path.strip()
    if len(s) > 256 or "`" in s or "Debe" in s or "nombre" in s or "talla" in s:
        return False
    if s in (":memory:", ""):
        return False
    return s.endswith(".duckdb") or ".duckdb" in s or "/" in s or s == "telegram.duckdb"


def _normalize_db_to_db_folder(raw: str, repo_root: Path) -> str:
    """Normaliza la ruta de BD: extrae el nombre del archivo y devuelve db/<nombre>.duckdb."""
    s = (raw or "").strip()
    if not s or not _valid_db_path(s):
        return "db/telegram.duckdb"
    # Si ya está en db/<algo>, mantener (puede ser db/finanz.duckdb)
    if s.replace("\\", "/").startswith("db/"):
        return s
    # Extraer nombre del archivo (ej. finanz.duckdb desde /path/to/finanz.duckdb)
    name = Path(s).name
    if not name.lower().endswith(".duckdb"):
        name = name + ".duckdb" if name else "telegram.duckdb"
    return f"db/{name}"


def _resolve_db_path_prefer_existing(
    raw: str,
    repo_root: Path,
    console: Console | None = None,
) -> str:
    """
    Valida la entrada y, si ya existe un .duckdb con el mismo nombre bajo db/, usa esa ruta
    (no fuerza db/<solo_nombre> si hay otra copia en db/private/...).
    No sobrescribe archivos existentes: solo elige la ruta correcta antes de crear uno nuevo.
    """
    s = (raw or "").strip()
    if not s or not _valid_db_path(s):
        return _normalize_db_to_db_folder("telegram.duckdb", repo_root)

    rr = repo_root.resolve()

    # 1) Ruta literal (relativa al repo o absoluta) que apunta a un fichero existente
    cand = Path(s)
    if not cand.is_absolute():
        full = (rr / cand).resolve()
    else:
        full = cand.resolve()
    if full.is_file() and full.suffix.lower() == ".duckdb":
        try:
            rel = full.relative_to(rr)
            out = str(rel).replace("\\", "/")
        except ValueError:
            out = str(full)
        if console:
            console.print(f"[green]✓[/] BD existente: [dim]{out}[/]")
        return out

    norm = _normalize_db_to_db_folder(s, repo_root)
    norm_full = rr / norm.replace("/", os.sep)
    if norm_full.is_file():
        if console:
            console.print(f"[green]✓[/] BD existente: [dim]{norm}[/]")
        return norm

    # 2) Mismo nombre de archivo: buscar db/**/<nombre>.duckdb
    name = Path(norm).name
    if not name.lower().endswith(".duckdb"):
        name = name + ".duckdb"
    try:
        matches = sorted(
            rr.glob(f"db/**/{name}"),
            key=lambda p: (
                0 if "private" in str(p).replace("\\", "/") else 1,
                -len(str(p)),
            ),
        )
    except Exception:
        matches = []

    if len(matches) == 1:
        rel = matches[0].relative_to(rr)
        out = str(rel).replace("\\", "/")
        if console:
            console.print(
                f"[green]✓[/] Ya hay una BD [bold]{escape(name)}[/] en el repo → "
                f"se usa [dim]{out}[/] (no se crea otra en db/ raíz)."
            )
        return out
    if len(matches) > 1:
        rel = matches[0].relative_to(rr)
        out = str(rel).replace("\\", "/")
        if console:
            console.print("[yellow]Varias bases con el mismo nombre; se prioriza ruta bajo private/ o la más específica.[/]")
            for m in matches[:6]:
                try:
                    console.print(f"  [dim]{m.relative_to(rr)}[/]")
                except ValueError:
                    pass
            console.print(f"[green]✓[/] Se usa [bold]{escape(out)}[/]")
        return out

    return norm


def load_config() -> dict[str, Any] | None:
    """Carga preferencias desde ~/.config/duckclaw/wizard_config.json. Siempre revisar primero antes de configurar desde 0."""
    path = _config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        out = {}
        for k in CONFIG_KEYS:
            if k not in data:
                continue
            v = data[k]
            if k == "db_path":
                env_db = (os.environ.get("DUCKCLAW_DB_PATH") or "").strip()
                if env_db and _valid_db_path(env_db):
                    out["db_path"] = env_db
                else:
                    out["db_path"] = v if _valid_db_path(v) else "telegram.duckdb"
            elif k in ("save_grpo_traces", "send_to_langsmith", "save_conversation_traces"):
                out[k] = bool(v) if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes", "y", "sí", "si")
            elif k == "conversation_traces_format":
                raw = (str(v).strip().lower() if v else "sft")
                out[k] = raw if raw in ("grpo", "sft") else "sft"
            elif k == "gateway_pm2_name":
                out[k] = str(v).strip() if v else ""
            else:
                out[k] = v if v is not None else ""
        if "last_deploy_provider" in data and isinstance(data["last_deploy_provider"], str):
            p = data["last_deploy_provider"].strip().lower()
            if p in DEPLOY_PROVIDERS:
                out["last_deploy_provider"] = p
        if "available_deploy_providers" in data and isinstance(data["available_deploy_providers"], list):
            out["available_deploy_providers"] = [x for x in data["available_deploy_providers"] if x in DEPLOY_PROVIDERS]
        return out
    except Exception:
        return None


def _detect_available_deploy_providers() -> list[str]:
    """Detecta qué proveedores de persistencia están disponibles en este equipo."""
    available: list[str] = []
    if shutil.which("pm2") is not None:
        available.append("pm2")
    if platform.system() == "Linux" and (shutil.which("systemctl") or (os.path.exists("/run/systemd/system"))):
        available.append("systemd")
    if platform.system() == "Windows":
        available.append("windows")
    return available


def _save_available_deploy_providers(providers: list[str]) -> None:
    """Guarda la lista de proveedores detectados en wizard_config.json."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    data["available_deploy_providers"] = [p for p in providers if p in DEPLOY_PROVIDERS]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_deploy_service_running(name: str) -> tuple[bool, str]:
    """Comprueba si ya existe un servicio con este nombre. Devuelve (existe, proveedor)."""
    if shutil.which("pm2") is not None:
        r = subprocess.run(
            ["pm2", "describe", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and name in (r.stdout or ""):
            return True, "pm2"
    if platform.system() == "Linux" and shutil.which("systemctl") is not None:
        unit = name.lower().replace(" ", "-") + ".service"
        r = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            capture_output=True,
            timeout=3,
        )
        if r.returncode == 0:
            return True, "systemd"
    return False, ""


def _ensure_pm2_inference_service(script_path: Path, cwd: Path) -> str:
    """Arranca DuckClaw-Inference (start_mlx.sh) con PM2 si no está ya en marcha. Devuelve mensaje para el usuario."""
    if not shutil.which("pm2"):
        return "pm2 no encontrado; no se pudo crear el servicio de inferencia."
    exists, _ = _is_deploy_service_running(INFERENCE_SERVICE_NAME)
    if exists:
        return f"{INFERENCE_SERVICE_NAME} ya está en PM2. Nada que hacer."
    script_str = str(script_path.resolve())
    try:
        # PM2: usar bash para .sh por si no tiene +x; -- no interpretar opciones en el script
        r = subprocess.run(
            ["pm2", "start", "bash", "--name", INFERENCE_SERVICE_NAME, "--cwd", str(cwd), "--", script_str],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(cwd),
        )
        if r.returncode != 0:
            return f"Error al arrancar {INFERENCE_SERVICE_NAME}: {r.stderr or r.stdout or 'unknown'}"
        return f"pm2: started '{INFERENCE_SERVICE_NAME}' (inferencia MLX). Usa 'pm2 logs {INFERENCE_SERVICE_NAME}'."
    except Exception as e:
        return f"Error ejecutando PM2 para inferencia: {e}"


def _persist_gateway_pm2_name(name: str) -> None:
    """Guarda el nombre PM2 del Gateway en wizard_config.json (merge, no borra otras claves)."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    n = (name or "").strip() or GATEWAY_SERVICE_NAME
    data["gateway_pm2_name"] = n
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_gateway_service_name(
    service_name: str,
    state: dict[str, Any],
    repo_root: Path | None = None,
) -> bool:
    """True si el nombre PM2 corresponde al Gateway (default, guardado en wizard o listado en api_gateways_pm2.json)."""
    n = (service_name or "").strip()
    if not n:
        return False
    if n == GATEWAY_SERVICE_NAME:
        return True
    saved = (state.get("gateway_pm2_name") or "").strip()
    if bool(saved) and n == saved:
        return True
    if repo_root is not None:
        try:
            p = repo_root / "config" / "api_gateways_pm2.json"
            if p.is_file():
                raw = json.loads(p.read_text(encoding="utf-8"))
                for a in raw.get("apps") or []:
                    if isinstance(a, dict) and (a.get("name") or "").strip() == n:
                        return True
        except Exception:
            pass
    return False


def _tcp_port_in_use(port: int) -> bool:
    """True si no se puede hacer bind a 0.0.0.0:port (otro proceso escuchando)."""
    if port <= 0 or port > 65535:
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
    except OSError:
        return True
    return False


def _lsof_listen_hint(port: int) -> str:
    """Salida de lsof para depurar [Errno 48] (macOS/Linux)."""
    if platform.system() not in ("Darwin", "Linux"):
        return ""
    for cmd in (
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        ["lsof", "-nP", f"-i:{port}"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            out = (r.stdout or "").strip()
            if out:
                return out
        except Exception:
            pass
    return ""


def _listen_pids_on_port(port: int) -> list[int]:
    """PIDs que escuchan en TCP `port` (macOS/Linux)."""
    if platform.system() not in ("Darwin", "Linux"):
        return []
    for cmd in (
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        ["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"],
        ["lsof", "-ti", f":{port}"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            if r.returncode != 0:
                continue
            pids: list[int] = []
            for line in (r.stdout or "").splitlines():
                line = (line or "").strip()
                if line.isdigit():
                    pids.append(int(line))
            if pids:
                return pids
        except Exception:
            pass
    return []


def _pm2_pids_for_app_name(name: str) -> set[int]:
    """PIDs que PM2 asocia a esta app (nombre del proceso)."""
    out: set[int] = set()
    n = (name or "").strip()
    if not n or shutil.which("pm2") is None:
        return out
    try:
        r = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return out
        import json as _json

        for p in _json.loads(r.stdout or "[]"):
            if (p.get("name") or "").strip() != n:
                continue
            pid = p.get("pid")
            if pid:
                try:
                    out.add(int(pid))
                except (TypeError, ValueError):
                    pass
            pe = p.get("pm2_env") or {}
            for key in ("pm_pid", "pid"):
                v = pe.get(key)
                if v:
                    try:
                        out.add(int(v))
                    except (TypeError, ValueError):
                        pass
    except Exception:
        pass
    return out


def _wizard_resolve_gateway_conflicts(console: Console, repo_root: Path) -> None:
    """
    Analiza config/api_gateways_pm2.json, muestra conflictos (puerto/DuckDB),
    opcionalmente puertos ocupados en el host (bind + lsof) y guía para corregir.
    """
    try:
        from duckclaw.ops.manager import analyze_gateway_cluster_conflicts, save_gateway_cluster_config
    except Exception as e:
        console.print(f"[red]No se pudo cargar duckclaw.ops.manager: {e}[/]")
        return

    cwd = str(repo_root.resolve())
    gw_path = repo_root / "config" / "api_gateways_pm2.json"
    if not gw_path.is_file():
        console.print(
            Panel(
                "No existe config/api_gateways_pm2.json. "
                "Crea uno con la configuración del API Gateway en el asistente o con "
                "[dim]duckops serve --pm2 --gateway[/].",
                title="Sin definición de gateways",
                border_style="yellow",
            )
        )
        return

    report = analyze_gateway_cluster_conflicts(cwd)
    apps: list[dict[str, Any]] = copy.deepcopy(report["apps"])
    if not apps:
        console.print("[yellow]No hay entradas en api_gateways_pm2.json.[/]")
        return

    console.print(
        Panel(
            "[bold]Conflictos típicos[/]\n"
            "• [Errno 48] address already in use: mismo puerto en dos gateways en el JSON, "
            "u otro proceso fuera de PM2 usando ese puerto.\n"
            "• DuckDB: dos gateways con la misma ruta → locks / errores de concurrencia.\n"
            "[dim]Finanz en 8000 y TheMind en 8080: usa [bold]BD distinta[/] por gateway "
            "(p. ej. finanzdb1.duckdb vs the_mind.duckdb) para evitar locks DuckDB.[/]",
            title="Resolver conflictos — API Gateways (PM2)",
            border_style="cyan",
        )
    )

    def _collect_used_ports(exclude_names: set[str] | None = None) -> set[int]:
        ex = exclude_names or set()
        u: set[int] = set()
        for a in apps:
            if not isinstance(a, dict):
                continue
            n = (a.get("name") or "").strip()
            if n in ex:
                continue
            p = int(a.get("port") or 0)
            if p > 0:
                u.add(p)
        return u

    def _next_free_port(used: set[int], start: int) -> int:
        p = max(1, min(int(start), 65535))
        while p <= 65535 and p in used:
            p += 1
        return min(p, 65535)

    def _find_app(gw_name: str) -> dict[str, Any] | None:
        for a in apps:
            if isinstance(a, dict) and (a.get("name") or "").strip() == gw_name:
                return a
        return None

    dup_ports = report.get("duplicate_ports") or {}
    dup_dbs = report.get("duplicate_databases") or {}

    if dup_ports:
        for pnum, group_names in sorted(dup_ports.items()):
            console.print(
                f"[red]Puerto {pnum} repetido en el JSON:[/] {', '.join(escape(str(x)) for x in group_names)}"
            )
            hint = _lsof_listen_hint(pnum)
            if hint:
                console.print(Panel(escape(hint[:6000]), title=f"lsof :{pnum}", border_style="dim"))

    if dup_dbs:
        for db_key, group_names in sorted(dup_dbs.items()):
            console.print(
                f"[red]Misma DUCKCLAW_DB_PATH (resuelta):[/] {', '.join(escape(str(x)) for x in group_names)}"
            )
            console.print(f"  [dim]{escape(db_key)}[/]")

    # Diagnóstico de puerto: si ya escucha el propio PM2 de este gateway, no es conflicto.
    for a in apps:
        if not isinstance(a, dict):
            continue
        n = (a.get("name") or "").strip()
        p = int(a.get("port") or 0)
        if p <= 0:
            continue
        if _tcp_port_in_use(p):
            listen_pids = _listen_pids_on_port(p)
            pm2_pids = _pm2_pids_for_app_name(n)
            if listen_pids and pm2_pids and (set(listen_pids) & pm2_pids):
                console.print(
                    f"[dim]Puerto {p} ([bold]{escape(n)}[/]): lo usa el propio proceso en PM2 "
                    "(normal si el gateway ya está en marcha). No indica conflicto con otro servicio.[/]"
                )
                continue
            console.print(
                f"[yellow]⚠️  El puerto {p} ([bold]{escape(n)}[/]) parece ocupado en este host "
                "(no se puede hacer bind). Revisa qué escucha ahí:[/]"
            )
            hint = _lsof_listen_hint(p)
            if hint:
                console.print(Panel(escape(hint[:6000]), title=f"lsof :{p}", border_style="dim"))
            console.print(
                "[dim]Si es un proceso antiguo, deténlo o cambia el puerto de este gateway. "
                "`pm2 restart` no libera el puerto si otro binario lo tiene.[/]"
            )

    if not report.get("has_conflicts"):
        console.print("[green]✓[/] No hay duplicados de puerto ni de DuckDB en api_gateways_pm2.json.")
        return

    if not Confirm.ask("¿Corregir ahora asignando puertos y/o rutas DuckDB distintas?", default=True):
        return

    # ── Puertos duplicados en el JSON ─────────────────────────────
    for pnum, group_names in sorted(dup_ports.items()):
        gset = set(group_names)
        used = _collect_used_ports(exclude_names=gset)
        sorted_gw = sorted(group_names)
        for i, gwn in enumerate(sorted_gw):
            app = _find_app(gwn)
            if not app:
                continue
            cur = int(app.get("port") or 0)
            if i == 0:
                default_s = str(cur or pnum)
                pr = Prompt.ask(
                    f"Puerto HTTP para [bold]{escape(gwn)}[/] (antes compartía {pnum})",
                    default=default_s,
                ).strip()
            else:
                sug = _next_free_port(used, (cur or pnum) + i)
                pr = Prompt.ask(
                    f"Puerto HTTP para [bold]{escape(gwn)}[/] (distinto del resto)",
                    default=str(sug),
                ).strip()
            try:
                np = int(pr)
                if 1 <= np <= 65535:
                    app["port"] = np
                    used.add(np)
                else:
                    console.print("[yellow]Puerto fuera de rango; se omite.[/]")
            except ValueError:
                console.print("[yellow]Valor no numérico; se omite.[/]")

    # ── DuckDB compartida ───────────────────────────────────────
    for _db_key, group_names in sorted(dup_dbs.items()):
        sorted_gw = sorted(group_names)
        for i, gwn in enumerate(sorted_gw):
            app = _find_app(gwn)
            if not app:
                continue
            env = app.get("env")
            if not isinstance(env, dict):
                env = {}
                app["env"] = env
            cur = (env.get("DUCKCLAW_DB_PATH") or "").strip()
            safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", gwn).strip("_").lower() or "gateway"
            if not safe_slug.endswith(".duckdb"):
                default_db = f"db/{safe_slug}.duckdb"
            else:
                default_db = f"db/{safe_slug}"
            if i == 0:
                pr = Prompt.ask(
                    f"DUCKCLAW_DB_PATH para [bold]{escape(gwn)}[/] (Enter=mantener)",
                    default=cur or default_db,
                ).strip()
            else:
                pr = Prompt.ask(
                    f"DUCKCLAW_DB_PATH para [bold]{escape(gwn)}[/] (ruta distinta)",
                    default=default_db if not cur else f"db/{safe_slug}_2.duckdb",
                ).strip()
            if pr:
                env["DUCKCLAW_DB_PATH"] = _normalize_db_to_db_folder(pr, repo_root)

    try:
        save_gateway_cluster_config(cwd, apps)
        console.print("[green]✓[/] Guardado config/api_gateways_pm2.json y config/ecosystem.api.config.cjs")
    except Exception as e:
        console.print(f"[red]Error al guardar: {e}[/]")
        return

    if shutil.which("pm2") and Confirm.ask(
        "¿Reiniciar en PM2 cada gateway con --update-env?",
        default=True,
    ):
        for a in apps:
            if isinstance(a, dict) and (a.get("name") or "").strip():
                nm = (a.get("name") or "").strip()
                r = subprocess.run(
                    ["pm2", "restart", nm, "--update-env"],
                    capture_output=True,
                    text=True,
                    timeout=90,
                    cwd=cwd,
                )
                if r.returncode == 0:
                    console.print(f"[green]✓[/] pm2 restart {escape(nm)}")
                else:
                    console.print(
                        f"[yellow]pm2 restart {escape(nm)}:[/] {escape((r.stderr or r.stdout or '')[:500])}"
                    )


def _save_last_deploy_provider(provider: str) -> None:
    """Guarda la última opción de proveedor de persistencia usada en wizard_config.json."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    data["last_deploy_provider"] = provider.strip().lower()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _edit_gateway_service(
    console: Console,
    state: dict[str, Any],
    repo_root: Path,
    *,
    preselected_pm2_name: str | None = None,
    skip_name_prompt: bool = False,
) -> None:
    """Gestiona DuckClaw-Gateway (spec FLUJO_VIDA_DATO: services/api-gateway)."""
    gw_json = repo_root / "config" / "api_gateways_pm2.json"
    if gw_json.is_file():
        try:
            raw = json.loads(gw_json.read_text(encoding="utf-8"))
            reg = raw.get("apps") if isinstance(raw, dict) else None
            if isinstance(reg, list) and reg:
                console.print("[dim]Gateways ya definidos en config/api_gateways_pm2.json:[/]")
                for a in reg:
                    if isinstance(a, dict) and a.get("name"):
                        console.print(
                            f"  • [bold]{escape(str(a.get('name')))}[/] → "
                            f"puerto [cyan]{a.get('port', '?')}[/]"
                        )
        except Exception:
            pass
        try:
            from duckclaw.ops.manager import analyze_gateway_cluster_conflicts

            rep = analyze_gateway_cluster_conflicts(str(repo_root.resolve()))
            if rep.get("has_conflicts"):
                console.print(
                    Panel(
                        "Hay conflictos en api_gateways_pm2.json (puerto o DuckDB duplicados). "
                        "Sal al menú inicial y usa la opción [bold]r[/], o ejecuta:\n"
                        "  [dim]python scripts/duckclaw_setup_wizard.py --resolve-gateways[/]",
                        title="⚠️ Gateways: revisar conflictos",
                        border_style="yellow",
                    )
                )
        except Exception:
            pass

    ps = (preselected_pm2_name or "").strip()
    if ps:
        gateway_name = ps
        state["gateway_pm2_name"] = gateway_name
        _persist_gateway_pm2_name(gateway_name)
    elif skip_name_prompt:
        gateway_name = (state.get("gateway_pm2_name") or "").strip() or GATEWAY_SERVICE_NAME
    else:
        merged_cfg = load_config() or {}
        if not isinstance(merged_cfg, dict):
            merged_cfg = {}
        hint = (merged_cfg.get("gateway_pm2_name") or "").strip() or GATEWAY_SERVICE_NAME
        console.print(
            f"[dim]Nombre estándar del spec: [bold]{GATEWAY_SERVICE_NAME}[/]. "
            "Elige ese u otro por instancia (varios gateways = varios nombres/puertos).[/]"
        )
        use_std, nav = _confirm_with_nav(
            console,
            f"¿Usar [bold]{GATEWAY_SERVICE_NAME}[/] como nombre del proceso PM2?",
            default=True,
        )
        if nav is not None:
            return
        if use_std:
            gateway_name = GATEWAY_SERVICE_NAME
        else:
            gateway_name = Prompt.ask(
                "Nombre PM2 personalizado",
                default=hint,
            ).strip() or GATEWAY_SERVICE_NAME
        state["gateway_pm2_name"] = gateway_name
        _persist_gateway_pm2_name(gateway_name)

    port_default = "8000"
    if gw_json.is_file():
        try:
            raw = json.loads(gw_json.read_text(encoding="utf-8"))
            for a in raw.get("apps") or []:
                if isinstance(a, dict) and (a.get("name") or "").strip() == gateway_name:
                    port_default = str(int(a.get("port") or 8000))
                    break
        except Exception:
            pass
    console.print(
        f"[dim]Puerto sugerido: [bold]{port_default}[/] "
        "(desde config/api_gateways_pm2.json si ya existía esta entrada; por defecto 8000 si es nuevo). "
        "Cada gateway debe usar un puerto distinto (p. ej. 8000, 8080, 8001).[/]"
    )
    port_raw = Prompt.ask(
        "Puerto HTTP",
        default=port_default,
    ).strip() or port_default
    try:
        gw_port = int(port_raw)
        if not (1 <= gw_port <= 65535):
            raise ValueError
    except Exception:
        console.print("[yellow]Puerto inválido; uso 8000.[/]")
        gw_port = 8000

    console.print(Panel(
        f"API Gateway (microservicio unificado)\n"
        f"services/api-gateway → Redis → DB Writer → DuckDB\n"
        f"Proceso PM2: [bold]{escape(gateway_name)}[/]  Puerto: [bold]{gw_port}[/]\n"
        f"[dim]Varios gateways conviven en config/api_gateways_pm2.json; no se borran otros PM2.[/]",
        title="DuckClaw Gateway",
        border_style="cyan",
    ))
    db_path = _normalize_db_to_db_folder(
        state.get("db_path") or os.environ.get("DUCKCLAW_DB_PATH", "db/duckclaw.duckdb"),
        repo_root,
    )
    redis_url = os.environ.get("REDIS_URL") or os.environ.get("DUCKCLAW_REDIS_URL", "redis://localhost:6379/0")
    save_traces_env = os.environ.get("DUCKCLAW_SAVE_CONVERSATION_TRACES", "true").strip().lower()
    save_traces_current = save_traces_env in ("true", "1", "yes")
    traces_fmt = (os.environ.get("DUCKCLAW_CONVERSATION_TRACES_FORMAT", "sft") or "sft").strip().lower()
    if traces_fmt not in ("grpo", "sft"):
        traces_fmt = "sft"
    console.print(f"DB path: [dim]{db_path}[/]  Redis: [dim]{redis_url}[/]  Trazas: [dim]{'sí' if save_traces_current else 'no'}[/]  Formato: [dim]{traces_fmt}[/]")

    while True:
        if Confirm.ask("¿Regenerar config y reiniciar Gateway?", default=True):
            _write_env_file(repo_root, "DUCKCLAW_DB_PATH", db_path)
            _write_env_file(repo_root, "REDIS_URL", redis_url)
            _write_env_file(repo_root, "DUCKCLAW_SAVE_CONVERSATION_TRACES", "true" if save_traces_current else "false")
            _write_env_file(repo_root, "DUCKCLAW_CONVERSATION_TRACES_FORMAT", traces_fmt)
            try:
                from duckclaw.ops.manager import serve
                code = serve(
                    host="0.0.0.0",
                    port=gw_port,
                    pm2=True,
                    gateway=True,
                    name=gateway_name,
                    cwd=str(repo_root),
                    delete_pm2_name=None,
                    gateway_db_path=db_path,
                )
                if code == 0:
                    console.print("[green]✓[/] Gateway configurado y reiniciado.")
                else:
                    console.print(f"[yellow]Revisa los logs: pm2 logs {escape(gateway_name)}[/]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/]")
                console.print("[dim]Ejecuta manualmente: duckops serve --pm2 --gateway[/]")
            return
        # No regenerar: permitir editar ruta DB, Redis, guardar trazas, etc.
        console.print("[dim]Edita los valores (Enter = mantener actual).[/]")
        gateway_name = Prompt.ask("Nombre proceso PM2 (Gateway)", default=gateway_name).strip() or gateway_name
        state["gateway_pm2_name"] = gateway_name
        _persist_gateway_pm2_name(gateway_name)
        new_db = Prompt.ask("DUCKCLAW_DB_PATH", default=db_path).strip() or db_path
        db_path = _normalize_db_to_db_folder(new_db, repo_root)
        new_redis = Prompt.ask("REDIS_URL", default=redis_url).strip() or redis_url
        redis_url = new_redis
        save_traces_yes = Confirm.ask(
            "¿Guardar trazas de conversaciones en train/conversation_traces/ (datalake año/mes/día)?",
            default=save_traces_current,
        )
        save_traces_current = save_traces_yes
        if save_traces_yes:
            fmt_prompt = Prompt.ask("Formato de trazas (sft | grpo)", default=traces_fmt).strip().lower() or traces_fmt
            traces_fmt = "grpo" if fmt_prompt == "grpo" else "sft"
        _write_env_file(repo_root, "DUCKCLAW_DB_PATH", db_path)
        _write_env_file(repo_root, "REDIS_URL", redis_url)
        _write_env_file(repo_root, "DUCKCLAW_SAVE_CONVERSATION_TRACES", "true" if save_traces_yes else "false")
        _write_env_file(repo_root, "DUCKCLAW_CONVERSATION_TRACES_FORMAT", traces_fmt)
        os.environ["DUCKCLAW_DB_PATH"] = db_path
        os.environ["REDIS_URL"] = redis_url
        os.environ["DUCKCLAW_SAVE_CONVERSATION_TRACES"] = "true" if save_traces_yes else "false"
        os.environ["DUCKCLAW_CONVERSATION_TRACES_FORMAT"] = traces_fmt
        console.print(f"[green]✓[/] .env actualizado: DUCKCLAW_DB_PATH={db_path}, REDIS_URL=[dim]...[/], trazas={'sí' if save_traces_yes else 'no'}, formato={traces_fmt}")
        if not Confirm.ask("¿Seguir editando este servicio?", default=False):
            return


def _offer_gateway_pm2_if_pm2(console: Console, state: dict[str, Any], repo_root: Path) -> None:
    """
    Tras la configuración completa: ofrece abrir el flujo del API Gateway (nombre PM2, BD, Redis).
    No depende de haber elegido un proceso en el menú inicial (opción 0).
    """
    if not shutil.which("pm2"):
        return
    merged = load_config() or {}
    if not isinstance(merged, dict):
        merged = {}
    save_conv = state.get("save_conversation_traces", True)
    if isinstance(save_conv, str):
        save_conv = str(save_conv).lower() in ("true", "1", "yes", "y", "sí", "si")
    # Si guardan trazas de conversación (Gateway/API), sugerir sí por defecto
    default_yes = bool(save_conv)

    console.print()
    console.print(Panel(
        f"El API Gateway (FastAPI, n8n, Telegram vía Gateway) es un proceso PM2 distinto de "
        f"[bold]{DEPLOY_SERVICE_NAME}[/].\n"
        "Ahí defines nombre PM2, puerto, DUCKCLAW_DB_PATH y Redis; varios gateways se fusionan en "
        "config/api_gateways_pm2.json sin borrar otros procesos PM2.",
        title="API Gateway (spec FLUJO_VIDA_DATO)",
        border_style="cyan",
    ))
    yes, nav = _confirm_with_nav(
        console,
        "¿Abrir ahora la configuración del API Gateway?",
        default=default_yes,
    )
    if nav is not None or not yes:
        return
    saved_hint = (merged.get("gateway_pm2_name") or "").strip() or GATEWAY_SERVICE_NAME
    console.print(
        f"[dim]Nombre PM2 por defecto del spec: [bold]{GATEWAY_SERVICE_NAME}[/]. "
        f"Último guardado en wizard: [bold]{escape(str(saved_hint))}[/] (solo como sugerencia).[/]"
    )
    use_std, nav2 = _confirm_with_nav(
        console,
        f"¿Usar el nombre estándar [bold]{GATEWAY_SERVICE_NAME}[/] para este API Gateway?",
        default=True,
    )
    if nav2 is not None:
        return
    if use_std:
        state["gateway_pm2_name"] = GATEWAY_SERVICE_NAME
    else:
        custom = Prompt.ask(
            "Nombre PM2 personalizado",
            default=saved_hint,
        ).strip() or saved_hint
        state["gateway_pm2_name"] = custom
    _persist_gateway_pm2_name(state["gateway_pm2_name"])
    _edit_gateway_service(console, state, repo_root, skip_name_prompt=True)


def _edit_db_writer_service(console: Console, state: dict[str, Any], repo_root: Path) -> None:
    """Gestiona DuckClaw-DB-Writer (spec FLUJO_VIDA_DATO: services/db-writer)."""
    console.print(Panel(
        "Consumidor de duckdb_write_queue (Redis → DuckDB)",
        title=DB_WRITER_SERVICE_NAME,
        border_style="cyan",
    ))
    db_path = _normalize_db_to_db_folder(
        state.get("db_path") or os.environ.get("DUCKCLAW_DB_PATH", "db/duckclaw.duckdb"),
        repo_root,
    )
    redis_url = os.environ.get("REDIS_URL") or os.environ.get("DUCKCLAW_REDIS_URL", "redis://localhost:6379/0")
    new_db = Prompt.ask("DUCKDB_PATH", default=db_path).strip() or db_path
    new_db = _normalize_db_to_db_folder(new_db, repo_root)
    new_redis = Prompt.ask("REDIS_URL", default=redis_url).strip() or redis_url
    _write_env_file(repo_root, "DUCKCLAW_DB_PATH", new_db)
    _write_env_file(repo_root, "REDIS_URL", new_redis)
    if not Confirm.ask("¿Generar/actualizar ecosystem.db-writer.config.cjs?", default=True):
        return
    venv_python = os.path.abspath(sys.executable)
    db_writer_dir = repo_root / "services" / "db-writer"
    abs_db = str((repo_root / new_db).resolve()) if not Path(new_db).is_absolute() else new_db
    config_content = f"""/**
 * PM2 config for DuckClaw DB Writer (spec FLUJO_VIDA_DATO).
 * Consumidor: Redis duckdb_write_queue → DuckDB.
 */
module.exports = {{
  apps: [
    {{
      name: "{DB_WRITER_SERVICE_NAME}",
      script: "{venv_python}",
      args: "main.py",
      cwd: "{db_writer_dir}",
      interpreter: "none",
      autorestart: true,
      watch: false,
      env: {{
        PYTHONPATH: "{repo_root}",
        REDIS_URL: "{new_redis}",
        DUCKDB_PATH: "{abs_db}",
      }},
    }},
  ],
}};
"""
    config_path = repo_root / "ecosystem.db-writer.config.cjs"
    config_path.write_text(config_content, encoding="utf-8")
    console.print(f"[green]✓[/] Config: [dim]{config_path}[/]")
    action_table = Table(show_header=False, box=None)
    action_table.add_column("", style="bold cyan", width=3)
    action_table.add_column("")
    action_table.add_row("1", "Reiniciar")
    action_table.add_row("2", "Iniciar")
    action_table.add_row("3", "Detener")
    action_table.add_row("s", "Omitir")
    console.print(action_table)
    action = Prompt.ask("Acción", choices=["1", "2", "3", "s"], default="s").strip().lower()
    if action == "1":
        subprocess.run(["pm2", "restart", DB_WRITER_SERVICE_NAME, "--update-env"], timeout=10)
        console.print("[green]✓[/] Reiniciado.")
    elif action == "2":
        subprocess.run(["pm2", "start", str(config_path)], timeout=15)
        console.print("[green]✓[/] Iniciado.")
    elif action == "3":
        subprocess.run(["pm2", "stop", DB_WRITER_SERVICE_NAME], timeout=10)
        console.print("[green]✓[/] Detenido.")


def _pm2_app_status(name: str) -> str:
    """Return PM2 status string for a named app, or 'no registrado'."""
    try:
        r = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            import json as _json
            procs = _json.loads(r.stdout or "[]")
            for p in procs:
                if p.get("name") == name:
                    return (p.get("pm2_env") or {}).get("status", "unknown")
    except Exception:
        pass
    return "no registrado"


def _edit_service_settings(
    console: Console,
    state: dict[str, Any],
    repo_root: Path,
    service_name: str,
    provider: str = "pm2",
) -> None:
    """Interactive sub-menu to edit and apply PM2 or Systemd service configuration."""
    _load_dotenv()
    # Pipeline (spec FLUJO_VIDA_DATO): Gateway y DB Writer tienen flujos específicos
    if _is_gateway_service_name(service_name, state, repo_root) and provider == "pm2":
        _edit_gateway_service(
            console,
            state,
            repo_root,
            preselected_pm2_name=service_name,
        )
        return
    if service_name == DB_WRITER_SERVICE_NAME and provider == "pm2":
        _edit_db_writer_service(console, state, repo_root)
        return
    venv_python = str(repo_root / ".venv" / "bin" / "python3")
    
    if provider == "pm2":
        status = _pm2_app_status(service_name)
    else:
        status = "unknown"
        if platform.system() == "Linux":
            unit = service_name.lower().replace(" ", "-") + ".service"
            r1 = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True, timeout=3)
            if r1.returncode != 4:
                status = r1.stdout.strip()
            else:
                r2 = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=3)
                if r2.returncode != 4:
                    status = r2.stdout.strip()
            if status == "unknown":
                status = "no registrado"

    console.print(Panel(
        f"Servicio ({provider}): [bold]{service_name}[/]  Estado: [{_status_style(status)}]{status}[/]",
        title="Editar servicio de persistencia",
        border_style="cyan",
    ))

    # ── Mostrar config actual (prioridad: .env → state, .env es lo que usa el Gateway)
    env_db = (os.environ.get("DUCKCLAW_DB_PATH") or "").strip() or None
    cur_db_display = _normalize_db_to_db_folder(
        env_db or state.get("db_path") or "telegram.duckdb", repo_root
    )
    cur = Table(title="Configuración actual", border_style="dim")
    cur.add_column("Parámetro", style="dim cyan")
    cur.add_column("Valor", style="white")
    cur.add_row(f"Nombre app {provider}", service_name)
    cur.add_row("Modo bot", state.get("bot_mode", "langgraph"))
    cur.add_row("DB path", cur_db_display)
    cur.add_row("Proveedor LLM", state.get("llm_provider") or "none_llm")
    cur.add_row("Modelo LLM", state.get("llm_model") or "-")
    cur.add_row("Token", _censor_token(state.get("token", "")) or "(usa TELEGRAM_BOT_TOKEN de .env)")
    console.print(cur)

    if not Confirm.ask("¿Editar estos parámetros?", default=True):
        return

    # ── App name ──────────────────────────────────────────────────────
    new_name = Prompt.ask(f"Nombre de la app {provider}", default=service_name).strip() or service_name

    # ── Bot mode ──────────────────────────────────────────────────────
    t = Table(show_header=False, box=None)
    t.add_column("", style="bold cyan", width=3)
    t.add_column("")
    t.add_row("1", "echo      – respuesta eco simple")
    t.add_row("2", "langgraph – LangGraph + memoria bicameral (recomendado)")
    console.print(t)
    cur_mode = state.get("bot_mode", "langgraph")
    mode_map = {"1": "echo", "2": "langgraph"}
    mode_default = "1" if cur_mode == "echo" else "2"
    mode_choice = Prompt.ask("Modo del bot", choices=["1", "2"], default=mode_default).strip()
    new_mode = mode_map.get(mode_choice, "langgraph")
    state["bot_mode"] = new_mode

    # ── DB path (prioridad: .env → state, .env es lo que usa el Gateway)
    env_db = (os.environ.get("DUCKCLAW_DB_PATH") or "").strip() or None
    cur_db = _normalize_db_to_db_folder(
        env_db or state.get("db_path") or "telegram.duckdb", repo_root
    )
    new_db_raw = Prompt.ask("Ruta DB (DuckDB)", default=cur_db).strip() or cur_db
    new_db = _resolve_db_path_prefer_existing(new_db_raw, repo_root, console)
    state["db_path"] = new_db

    # ── Token ────────────────────────────────────────────────────────
    cur_tok = state.get("token", "")
    if cur_tok:
        console.print(f"[dim]Token actual: {_censor_token(cur_tok)} — deja en blanco para conservarlo[/]")
    else:
        console.print("[dim]Déjalo en blanco para leer TELEGRAM_BOT_TOKEN desde .env[/]")
    new_tok = Prompt.ask("Token Telegram (Enter para mantener)", default="", password=True).strip()
    if new_tok:
        state["token"] = new_tok
        _write_env_file(repo_root, "TELEGRAM_BOT_TOKEN", new_tok)

    # ── LLM (solo si el modo lo requiere) ────────────────────────────
    new_provider = state.get("llm_provider") or "none_llm"
    new_model = state.get("llm_model") or ""
    new_url = state.get("llm_base_url") or ""
    if new_mode == "langgraph":
        prov_table = Table(show_header=False, box=None)
        for p in LLM_PROVIDERS:
            prov_table.add_row(f"  {p}")
        console.print(prov_table)
        new_provider = Prompt.ask("Proveedor LLM", default=new_provider).strip().lower() or "none_llm"
        new_model = Prompt.ask("Modelo LLM (opcional)", default=new_model or "").strip()
        new_url = Prompt.ask("URL base LLM (opcional)", default=new_url or "").strip()
        state["llm_provider"] = new_provider
        state["llm_model"] = new_model
        state["llm_base_url"] = new_url

    # ── Resumen tras editar ───────────────────────────────────────────
    summary = Table(title="Resumen del servicio", border_style="green")
    summary.add_column("Parámetro", style="bold green")
    summary.add_column("Valor", style="white")
    summary.add_row(f"App {provider}", new_name)
    summary.add_row("Modo bot", new_mode)
    summary.add_row("DB path", new_db)
    summary.add_row("Token", _censor_token(state.get("token", "")) or "(usa TELEGRAM_BOT_TOKEN de .env)")
    if new_mode == "langgraph":
        summary.add_row("Proveedor LLM", new_provider)
        summary.add_row("Modelo LLM", new_model or "-")
        summary.add_row("URL base LLM", new_url or "-")
    console.print(summary)

    # Persistir siempre (wizard_config.json + .env) para que la próxima vez recuerde la última BD
    fmt_traces = (state.get("conversation_traces_format", "sft") or "sft").strip().lower()
    if fmt_traces not in ("grpo", "sft"):
        fmt_traces = "sft"
    save_config(
        mode=state.get("mode", "quick"),
        channel=state.get("channel", "telegram"),
        bot_mode=new_mode,
        db_path=new_db,
        llm_provider=new_provider,
        llm_model=new_model,
        llm_base_url=new_url,
        save_grpo_traces=state.get("save_grpo_traces", False),
        send_to_langsmith=state.get("send_to_langsmith", False),
        save_conversation_traces=state.get("save_conversation_traces", True),
        conversation_traces_format=fmt_traces,
    )
    _write_env_file(repo_root, "DUCKCLAW_DB_PATH", new_db)
    save_conv = state.get("save_conversation_traces", True)
    if isinstance(save_conv, str):
        save_conv = str(save_conv).lower() in ("true", "1", "yes", "y", "sí", "si")
    _write_env_file(repo_root, "DUCKCLAW_SAVE_CONVERSATION_TRACES", "true" if save_conv else "false")
    _write_env_file(repo_root, "DUCKCLAW_CONVERSATION_TRACES_FORMAT", fmt_traces)
    _ensure_db_file_exists(repo_root, new_db, console)

    if provider == "pm2":
        # ── Generar ecosystem.core.config.cjs ────────────────────────────
        if not Confirm.ask("¿Generar/actualizar ecosystem.core.config.cjs?", default=True):
            return

        config_path = repo_root / "ecosystem.core.config.cjs"
        cwd = str(repo_root)
        config_content = f"""/**
 * PM2 config for DuckClaw Telegram bot (generated by wizard).
 * Start: pm2 start ecosystem.core.config.cjs
 * Token: guardado en .env (auto-cargado por el bot al iniciar).
 */
module.exports = {{
  apps: [
    {{
      name: "{new_name}",
      script: "{venv_python}",
      args: "-m duckclaw.graphs.telegram_bot",
      cwd: "{cwd}",
      interpreter: "none",
      autorestart: true,
      watch: false,
      max_restarts: 10,
      env: {{
        PYTHONPATH: "{cwd}",
        DUCKCLAW_DB_PATH: "{new_db}",
        DUCKCLAW_BOT_MODE: "{new_mode}",
        DUCKCLAW_LLM_PROVIDER: "{new_provider}",
        DUCKCLAW_LLM_MODEL: "{new_model}",
        DUCKCLAW_LLM_BASE_URL: "{new_url}",
      }},
    }},
  ],
}};
"""
        config_path.write_text(config_content, encoding="utf-8")
        console.print(f"[green]✓[/] Config generado: [dim]{config_path}[/]")
    else:
        # Systemd: guardar variables en .env
        _write_env_file(repo_root, "DUCKCLAW_BOT_MODE", new_mode)
        _write_env_file(repo_root, "DUCKCLAW_LLM_PROVIDER", new_provider)
        _write_env_file(repo_root, "DUCKCLAW_LLM_MODEL", new_model)
        _write_env_file(repo_root, "DUCKCLAW_LLM_BASE_URL", new_url)
        console.print(f"[green]✓[/] Variables guardadas en: [dim]{repo_root / '.env'}[/]")

    # ── Acción del servicio ────────────────────────────────────────────────────
    action_table = Table(show_header=False, box=None)
    action_table.add_column("", style="bold cyan", width=3)
    action_table.add_column("")
    action_table.add_row("1", f"Reiniciar  {new_name}")
    action_table.add_row("2", f"Iniciar    {new_name}")
    action_table.add_row("3", f"Detener    {new_name}")
    action_table.add_row("s", "Omitir (aplicar cambios más tarde)")
    console.print(action_table)
    action = Prompt.ask(f"Acción {provider}", choices=["1", "2", "3", "s"], default="s").strip().lower()
    
    if provider == "pm2":
        if action == "1":
            subprocess.run(["pm2", "restart", new_name, "--update-env"], timeout=10)
            console.print(f"[green]✓[/] Reiniciado.")
        elif action == "2":
            subprocess.run(["pm2", "start", str(config_path)], timeout=15)
            console.print(f"[green]✓[/] Iniciado.")
        elif action == "3":
            subprocess.run(["pm2", "stop", new_name], timeout=10)
            console.print(f"[green]✓[/] Detenido.")
    elif provider == "systemd":
        unit = new_name.lower().replace(" ", "-") + ".service"
        is_user = False
        if subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit], capture_output=True, timeout=3).returncode != 4:
            is_user = True
        
        cmd_prefix = ["systemctl", "--user"] if is_user else ["sudo", "systemctl"]
        if action == "1":
            subprocess.run(cmd_prefix + ["restart", new_name], timeout=15)
            console.print(f"[green]✓[/] Reiniciado.")
        elif action == "2":
            subprocess.run(cmd_prefix + ["start", new_name], timeout=15)
            console.print(f"[green]✓[/] Iniciado.")
        elif action == "3":
            subprocess.run(cmd_prefix + ["stop", new_name], timeout=15)
            console.print(f"[green]✓[/] Detenido.")


def _write_env_file(repo_root: Path, key: str, value: str) -> None:
    """Write or update a key=value in .env (project root), without adding quotes."""
    if key == "DUCKCLAW_DB_PATH":
        _write_env_file(repo_root, "DUCKDB_PATH", value)  # spec FLUJO_VIDA_DATO: db-writer usa DUCKDB_PATH
    env_path = repo_root / ".env"
    lines: list[str] = []
    found = False
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ensure_db_file_exists(repo_root: Path, db_path: str, console: Console | None = None) -> bool:
    """Crea el archivo .duckdb en db/ si no existe. Devuelve True si se creó o ya existía."""
    if not db_path or not _valid_db_path(db_path):
        return False
    p = Path(db_path)
    if not p.is_absolute():
        p = (repo_root / p).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        if console:
            try:
                rel = p.relative_to(repo_root.resolve())
                console.print(f"[dim]BD ya existente (no se modifica): {rel}[/]")
            except ValueError:
                console.print(f"[dim]BD ya existente (no se modifica): {p}[/]")
        return True
    _orig_path = sys.path.copy()
    try:
        sys.path.insert(0, str(repo_root))
        from duckclaw import DuckClaw
        _db = DuckClaw(str(p))
        _db.execute("SELECT 1")
        if console:
            console.print(f"[green]✓[/] BD creada: [dim]{p}[/]")
        return True
    except Exception as e:
        if console:
            console.print(f"[yellow]⚠[/] No se pudo crear la BD en {p}: {e}")
        return False
    finally:
        sys.path[:] = _orig_path


def _status_style(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "online":
        return "green"
    if s in ("stopped", "no registrado", "unknown"):
        return "yellow"
    return "red"


def save_config(
    mode: str,
    channel: str,
    bot_mode: str,
    db_path: str,
    llm_provider: str = "",
    llm_model: str = "",
    llm_base_url: str = "",
    save_grpo_traces: bool = False,
    send_to_langsmith: bool = False,
    save_conversation_traces: bool = True,
    conversation_traces_format: str = "sft",
) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = (conversation_traces_format or "sft").strip().lower()
    fmt = fmt if fmt in ("grpo", "sft") else "sft"
    prev: dict[str, Any] = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(prev, dict):
                prev = {}
        except Exception:
            prev = {}
    data = {
        "mode": mode,
        "channel": channel,
        "bot_mode": bot_mode,
        "db_path": db_path,
        "llm_provider": llm_provider or "",
        "llm_model": llm_model or "",
        "llm_base_url": llm_base_url or "",
        "save_grpo_traces": save_grpo_traces,
        "send_to_langsmith": send_to_langsmith,
        "save_conversation_traces": save_conversation_traces,
        "conversation_traces_format": fmt,
    }
    if isinstance(prev.get("gateway_pm2_name"), str) and prev["gateway_pm2_name"].strip():
        data["gateway_pm2_name"] = prev["gateway_pm2_name"].strip()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _censor_token(token: str) -> str:
    if not token:
        return "(empty)"
    t = token.strip()
    if len(t) <= 8:
        return "****"
    return f"{t[:4]}...{t[-4:]}"


def _validate_token_format(token: str) -> tuple[bool, str]:
    t = token.strip()
    if len(t) < 30:
        return False, "Token demasiado corto (esperado ~45+ caracteres)."
    if ":" not in t:
        return False, "Token inválido: debe contener ':' (formato id:secret)."
    if not TELEGRAM_TOKEN_PATTERN.match(t):
        return False, "Token inválido: formato esperado números:letras/números."
    return True, ""


def _validate_token_with_api(token: str) -> tuple[bool, str]:
    try:
        from telegram import Bot
    except ImportError:
        return True, ""
    import asyncio

    async def check() -> tuple[bool, str]:
        bot = Bot(token=token.strip())
        try:
            await bot.get_me()
            return True, ""
        except Exception as e:
            return False, str(e).strip() or type(e).__name__

    try:
        ok, err = asyncio.run(asyncio.wait_for(check(), timeout=API_VALIDATION_TIMEOUT))
        return ok, err
    except asyncio.TimeoutError:
        return False, "Timeout: Telegram no respondió a tiempo."
    except Exception as e:
        return False, str(e).strip() or type(e).__name__


def _check_dependencies(console: Console) -> bool:
    console.print("[bold cyan]Comprobando módulos Python...[/]")
    try:
        import duckclaw  # noqa: F401
    except Exception:
        console.print(
            Panel(
                "DuckClaw no está disponible ([bold]import duckclaw[/]).\n"
                "Desde la raíz del repo:\n"
                "  • [bold]uv sync[/]  (recomendado)\n"
                "  • o [bold]uv pip install -e . --no-build-isolation[/]",
                title="❌ Error",
                border_style="red",
            )
        )
        return False
    try:
        import telegram  # noqa: F401
    except Exception:
        console.print(
            Panel(
                "Falta [bold]python-telegram-bot[/] ([bold]import telegram[/]).\n"
                "Desde la raíz del repo:\n"
                "  • [bold]uv sync --extra telegram[/]\n"
                "  • o [bold]uv pip install -e \".[telegram]\" --no-build-isolation[/]\n"
                "  • o [bold]uv pip install python-telegram-bot[/]",
                title="❌ Error",
                border_style="red",
            )
        )
        return False
    console.print("[green]✓ Dependencias correctas.[/]")
    return True


def _check_langgraph_dependency(console: Console) -> bool:
    try:
        import langgraph  # noqa: F401
    except Exception:
        console.print(
            Panel(
                "El modo LangGraph requiere: pip install langgraph",
                title="❌ Falta LangGraph",
                border_style="red",
            )
        )
        return False
    console.print("[green]✓ LangGraph disponible.[/]")
    return True


def _validate_provider_config(
    console: Console,
    provider: str,
    model: str,
    base_url: str,
) -> tuple[bool, str]:
    if provider == "none_llm":
        return True, ""
    if provider == "openai":
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            return False, "OpenAI requiere OPENAI_API_KEY. Exporta la variable."
        return True, ""
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            return False, "Anthropic requiere ANTHROPIC_API_KEY. Exporta la variable."
        return True, ""
    if provider == "deepseek":
        if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
            return False, "DeepSeek requiere DEEPSEEK_API_KEY. Exporta la variable."
        return True, ""
    if provider == "huggingface":
        key = os.environ.get("HUGGINGFACE_API_KEY", "").strip() or os.environ.get("HF_TOKEN", "").strip()
        if not key:
            return False, "HuggingFace requiere HUGGINGFACE_API_KEY o HF_TOKEN. Exporta la variable."
        return True, ""
    if provider == "ollama":
        if not base_url.strip():
            return False, "Ollama requiere URL (ej. http://localhost:11434)."
        return True, ""
    if provider == "iotcorelabs":
        if not base_url.strip():
            return False, "IoTCoreLabs requiere URL del endpoint."
        return True, ""
    if provider == "mlx":
        if not base_url.strip():
            return False, "MLX requiere URL base del modelo (ej. http://127.0.0.1:8080/v1)."
        if not model.strip():
            return False, "MLX requiere nombre del modelo."
        return True, ""
    return False, f"Proveedor desconocido: {provider}"


def _ask_provider(console: Console, state: dict[str, Any]) -> str | None:
    """Devuelve nav (next/prev/quit) si el usuario escribe s/a/q en el primer prompt, o None."""
    provider_table = Table(title="Model provider (elige: Anthropic, OpenAI, DeepSeek, MLX, IoTCoreLabs)", border_style="cyan")
    provider_table.add_column("Opción", style="bold cyan")
    provider_table.add_column("Descripción", style="white")
    for p in LLM_PROVIDERS:
        desc = {
            "iotcorelabs": "IoTCoreLabs",
            "openai": "OpenAI API",
            "anthropic": "Anthropic API",
            "deepseek": "DeepSeek API",
            "huggingface": "HuggingFace Inference API / Dedicated Endpoints",
            "mlx": "MLX (servidor local OpenAI-compatible)",
            "ollama": "Ollama local",
            "none_llm": "Sin LLM (reglas + memoria DuckClaw)",
        }.get(p, p)
        provider_table.add_row(p, desc)
    console.print(provider_table)
    default_provider = state.get("llm_provider") or "none_llm"
    val, nav = _prompt_with_nav(
        console, "Proveedor",
        choices=None,
        default=default_provider,
    )
    if nav:
        return nav
    r = (val or "").strip().lower()
    state["llm_provider"] = r if r in LLM_PROVIDERS else default_provider
    model = state.get("llm_model") or ""
    base_url = state.get("llm_base_url") or ""
    if state["llm_provider"] == "openai":
        state["llm_model"] = Prompt.ask("Modelo OpenAI", default=model or "gpt-4o-mini").strip()
    elif state["llm_provider"] == "anthropic":
        state["llm_model"] = Prompt.ask("Modelo Anthropic", default=model or "claude-3-5-haiku-20241022").strip()
    elif state["llm_provider"] == "deepseek":
        default_model = model or os.environ.get("DEEPSEEK_MODEL", "").strip() or "deepseek-chat"
        state["llm_model"] = Prompt.ask("Modelo DeepSeek", default=default_model).strip()
    elif state["llm_provider"] == "huggingface":
        hf_key = os.environ.get("HUGGINGFACE_API_KEY", "").strip() or os.environ.get("HF_TOKEN", "").strip()
        if not hf_key:
            console.print("[yellow]Agrega HUGGINGFACE_API_KEY o HF_TOKEN en .env[/]")
        state["llm_model"] = Prompt.ask(
            "Modelo HuggingFace (repo_id)",
            default=model or "mistralai/Mistral-7B-Instruct-v0.3",
        ).strip()
        console.print("[dim]URL opcional: deja en blanco para Serverless API, o pega la URL de un Inference Endpoint dedicado[/]")
        state["llm_base_url"] = Prompt.ask("URL endpoint (opcional)", default=base_url or "").strip()
    elif state["llm_provider"] == "ollama":
        state["llm_base_url"] = Prompt.ask("URL Ollama", default=base_url or "http://localhost:11434").strip()
        state["llm_model"] = Prompt.ask("Modelo Ollama", default=model or "llama3.2").strip()
    elif state["llm_provider"] == "iotcorelabs":
        state["llm_base_url"] = Prompt.ask("URL endpoint IoTCoreLabs", default=base_url).strip()
        state["llm_model"] = Prompt.ask("Modelo / token", default=model).strip()
    elif state["llm_provider"] == "mlx":
        default_mlx_url = base_url.strip()
        if not re.match(r"^https?://", default_mlx_url):
            default_mlx_url = "http://127.0.0.1:8080/v1"
        if "8000" in default_mlx_url:
            default_mlx_url = default_mlx_url.replace("8000", "8080")
        state["llm_base_url"] = Prompt.ask(
            "URL base del modelo",
            default=default_mlx_url,
        ).strip()
        state["llm_model"] = Prompt.ask(
            "Nombre del modelo (vacío = usar el que expone el servidor)",
            default=model or "",
        ).strip()
    else:
        state["llm_model"] = model
        state["llm_base_url"] = base_url


def _section_index(section_id: str) -> int:
    return SECTION_IDS.index(section_id)


def _next_index(i: int, state: dict[str, Any]) -> int | None:
    """None = fin (ejecutar lanzamiento)."""
    if i >= len(SECTION_IDS) - 1:
        return None
    n = i + 1
    # Saltar provider si no langgraph
    if SECTION_IDS[n] == "provider" and state.get("bot_mode") != "langgraph":
        n += 1
    # Saltar grpo_traces si no langgraph
    if SECTION_IDS[n] == "grpo_traces" and state.get("bot_mode") != "langgraph":
        n += 1
    # Saltar validate_provider si no langgraph
    if SECTION_IDS[n] == "validate_provider" and state.get("bot_mode") != "langgraph":
        n += 1
    if n >= len(SECTION_IDS):
        return None
    return n


def _prev_index(i: int, state: dict[str, Any]) -> int:
    if i <= 0:
        return 0
    p = i - 1
    if SECTION_IDS[p] == "validate_provider" and state.get("bot_mode") != "langgraph":
        p -= 1
    if SECTION_IDS[p] == "grpo_traces" and state.get("bot_mode") != "langgraph":
        p -= 1
    if SECTION_IDS[p] == "provider" and state.get("bot_mode") != "langgraph":
        p -= 1
    return max(0, p)


def _section_progress(idx: int, state: dict[str, Any]) -> tuple[int, int]:
    """(número actual 1-based, total) considerando secciones saltadas."""
    order: list[int] = []
    for i in range(len(SECTION_IDS)):
        sid = SECTION_IDS[i]
        if sid == "provider" and state.get("bot_mode") != "langgraph":
            continue
        if sid == "grpo_traces" and state.get("bot_mode") != "langgraph":
            continue
        if sid == "validate_provider" and state.get("bot_mode") != "langgraph":
            continue
        order.append(i)
    try:
        pos = order.index(idx)
        return pos + 1, len(order)
    except ValueError:
        return idx + 1, len(order)


def _run_section(
    section_id: str,
    console: Console,
    state: dict[str, Any],
    repo_root: Path,
    bot_script: Path,
) -> tuple[bool, str, str | None]:
    """Ejecuta la sección. Devuelve (éxito, mensaje_error, nav). nav in (next, prev, quit) o None."""
    if section_id == "welcome":
        if state.get("_from_saved"):
            console.print(f"[dim]Preferencias cargadas desde {_config_path()}.[/]")
            if Confirm.ask("¿Usar estas preferencias y saltar al resumen?", default=True):
                state["_skip_to_summary"] = True
                state["_used_preferences_skip"] = True
                state["token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        return True, "", None

    if section_id == "mode":
        console.print(Panel("Modo", title="Modo", border_style="cyan"))
        t = Table()
        t.add_column("Opción", style="bold cyan")
        t.add_column("Descripción", style="white")
        t.add_row("quick", "Rápido")
        t.add_row("manual", "Manual")
        console.print(t)
        default_mode = state.get("mode") or "quick"
        val, nav = _prompt_with_nav(
            console, "Modo",
            choices=None,
            default=default_mode,
        )
        if nav:
            return True, "", nav
        r = (val or "").strip().lower()
        state["mode"] = r if r in ("quick", "manual") else default_mode
        return True, "", None

    if section_id == "channel":
        console.print(Panel("Canal", title="Canal", border_style="cyan"))
        default_channel = state.get("channel") or "telegram"
        val, nav = _prompt_with_nav(
            console, "Canal",
            choices=None,
            default=default_channel,
        )
        if nav:
            return True, "", nav
        state["channel"] = (val or "").strip().lower() or default_channel
        if state["channel"] != "telegram":
            return False, f"Canal '{state['channel']}' no implementado.", None
        return True, "", None

    if section_id == "bot_mode":
        console.print(Panel("Modo del bot", title="Modo del bot", border_style="cyan"))
        t = Table()
        t.add_column("Opción", style="bold cyan")
        t.add_column("Descripción", style="white")
        t.add_row("echo", "Echo")
        t.add_row("langgraph", "LangGraph")
        console.print(t)
        default_bot_mode = state.get("bot_mode") or "echo"
        val, nav = _prompt_with_nav(
            console, "Modo del bot",
            choices=None,
            default=default_bot_mode,
        )
        if nav:
            return True, "", nav
        r = (val or "").strip().lower()
        state["bot_mode"] = r if r in ("echo", "langgraph") else default_bot_mode
        return True, "", None

    if section_id == "provider":
        console.print(Panel("Proveedor LLM", title="Proveedor", border_style="cyan"))
        nav = _ask_provider(console, state)
        if nav:
            return True, "", nav
        return True, "", None

    if section_id == "deps":
        console.print(Panel("Dependencias", title="Dependencias", border_style="cyan"))
        if not _check_dependencies(console):
            return False, "Corrige las dependencias y vuelve a esta sección.", None
        if state.get("bot_mode") == "langgraph" and not _check_langgraph_dependency(console):
            return False, "Instala LangGraph para modo langgraph.", None
        return True, "", None

    if section_id == "token":
        console.print(
            Panel(
                "Origen del token de Telegram.\n"
                "[dim]No se incluye en wizard_config.json; puede guardarse solo en .env.[/]",
                title="Token de Telegram",
                border_style="cyan",
            )
        )
        _load_dotenv()
        token_from_env = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

        if token_from_env:
            console.print(
                f"[dim]Detectado [bold]TELEGRAM_BOT_TOKEN[/] en .env / entorno "
                f"({_censor_token(token_from_env)}).[/]"
            )
            use_env, nav = _confirm_with_nav(
                console,
                "¿Usar ese token desde .env (TELEGRAM_BOT_TOKEN)?",
                default=True,
            )
            if nav:
                return True, "", nav
            if use_env:
                state["token"] = token_from_env
            else:
                console.print("[dim]Introduce el token manualmente (oculto al escribir).[/]")
                val, nav_in = _prompt_with_nav(console, "TELEGRAM_BOT_TOKEN", password=True)
                if nav_in:
                    return True, "", nav_in
                state["token"] = (val or "").strip()
                if state.get("token"):
                    save_e, nav_s = _confirm_with_nav(
                        console,
                        "¿Sobrescribir TELEGRAM_BOT_TOKEN en .env con este valor?",
                        default=True,
                    )
                    if nav_s:
                        return True, "", nav_s
                    if save_e:
                        _write_env_file(repo_root, "TELEGRAM_BOT_TOKEN", state["token"])
                        os.environ["TELEGRAM_BOT_TOKEN"] = state["token"]
        else:
            console.print(
                "[yellow]No hay TELEGRAM_BOT_TOKEN en .env.[/]\n"
                "[dim]Pégalo aquí o añádelo al archivo .env y vuelve a esta sección (a=anterior).[/]"
            )
            val, nav = _prompt_with_nav(console, "TELEGRAM_BOT_TOKEN", password=True)
            if nav:
                return True, "", nav
            state["token"] = (val or "").strip()
            if state.get("token"):
                save_e, nav_s = _confirm_with_nav(
                    console,
                    "¿Guardar TELEGRAM_BOT_TOKEN en .env?",
                    default=True,
                )
                if nav_s:
                    return True, "", nav_s
                if save_e:
                    _write_env_file(repo_root, "TELEGRAM_BOT_TOKEN", state["token"])
                    os.environ["TELEGRAM_BOT_TOKEN"] = state["token"]

        if not state.get("token", "").strip():
            return False, "El token es obligatorio.", None
        ok, err = _validate_token_format(state["token"])
        if not ok:
            return False, err, None
        console.print("[green]✓ Formato correcto.[/]")
        do_check = Confirm.ask("¿Validar token con Telegram ahora?", default=True)
        if do_check:
            with console.status("Comprobando con Telegram...", spinner="dots"):
                ok_api, err_api = _validate_token_with_api(state["token"])
            if not ok_api:
                return False, f"Telegram rechazó el token: {err_api}", None
            console.print("[green]✓ Token validado.[/]")
        return True, "", None

    if section_id == "db_path":
        console.print(Panel("Ruta de la base de datos", title="DB", border_style="cyan"))
        console.print(
            "[dim]Puedes poner ruta completa bajo el repo (p. ej. db/private/…/finanz.duckdb). "
            "Si solo indicas el nombre y ya existe otro .duckdb con el mismo nombre en db/, "
            "se reutiliza ese archivo — no se crea uno nuevo en db/ raíz ni se sobrescribe.[/]"
        )
        # Prioridad: última ruta guardada en config (JSON) → env DUCKCLAW_DB_PATH → fallback
        saved_path = state.get("db_path") if _valid_db_path(state.get("db_path")) else None
        env_path = (os.environ.get("DUCKCLAW_DB_PATH") or "").strip() or None
        # Normalizar a db/<nombre> para la sugerencia (última usada)
        default_db = _normalize_db_to_db_folder(saved_path or env_path or "telegram.duckdb", repo_root)
        val, nav = _prompt_with_nav(console, "DUCKCLAW_DB_PATH", default=default_db)
        if nav:
            return True, "", nav
        raw = (val or "").strip() or "telegram.duckdb"
        state["db_path"] = _resolve_db_path_prefer_existing(raw, repo_root, console)
        _ensure_db_file_exists(repo_root, state["db_path"], console)
        return True, "", None

    if section_id == "grpo_traces":
        console.print(Panel("Trazas GRPO y LangSmith", title="Trazas GRPO", border_style="cyan"))
        console.print("[dim]Guarda trazas en train/grpo_olist_traces.jsonl. Tras classify_traces(), usa train/grpo_olist_rewarded.jsonl (con rewards) por defecto.[/]")
        console.print("[dim]LangSmith requiere LANGCHAIN_API_KEY en .env o entorno.[/]")
        default_save = state.get("save_grpo_traces", True)
        if isinstance(default_save, str):
            default_save = default_save.lower() in ("true", "1", "yes", "y", "sí", "si")
        save_yes, nav = _confirm_with_nav(console, "¿Guardar trazas GRPO en train/grpo_olist_traces.jsonl?", default=default_save)
        if nav:
            return True, "", nav
        state["save_grpo_traces"] = save_yes
        if save_yes:
            default_langsmith = state.get("send_to_langsmith", True)
            if isinstance(default_langsmith, str):
                default_langsmith = default_langsmith.lower() in ("true", "1", "yes", "y", "sí", "si")
            langsmith_yes, nav2 = _confirm_with_nav(
                console, "¿Subir trazas a LangSmith? (requiere LANGCHAIN_API_KEY)", default=default_langsmith
            )
            if nav2:
                return True, "", nav2
            state["send_to_langsmith"] = langsmith_yes
        else:
            state["send_to_langsmith"] = False
        return True, "", None

    if section_id == "conversation_traces":
        console.print(Panel("Trazas de conversaciones", title="Trazas de conversaciones (Gateway/API)", border_style="cyan"))
        console.print("[dim]Guarda cada turno en train/conversation_traces/YYYY/MM/DD/traces.jsonl cuando se use el API Gateway (n8n, Telegram vía Gateway).[/]")
        default_save = state.get("save_conversation_traces", True)
        if isinstance(default_save, str):
            default_save = default_save.lower() in ("true", "1", "yes", "y", "sí", "si")
        save_yes, nav = _confirm_with_nav(
            console, "¿Guardar trazas de conversaciones en train/conversation_traces/ (datalake año/mes/día)?", default=default_save
        )
        if nav:
            return True, "", nav
        state["save_conversation_traces"] = save_yes
        if save_yes:
            default_fmt = state.get("conversation_traces_format", "sft").strip().lower()
            if default_fmt not in ("grpo", "sft"):
                default_fmt = "sft"
            console.print("[dim]SFT: messages (system, user, assistant) para mlx_lm. GRPO: prompt + reward_metadata para TRL/Unsloth.[/]")
            fmt_prompt = Prompt.ask("Formato de trazas (sft | grpo)", default=default_fmt).strip().lower() or default_fmt
            state["conversation_traces_format"] = "grpo" if fmt_prompt == "grpo" else "sft"
        return True, "", None

    if section_id == "validate_provider":
        console.print(Panel("Validar proveedor", title="Validar proveedor", border_style="cyan"))
        prov = (state.get("llm_provider") or "none_llm").strip().lower()
        ok_prov, err_prov = _validate_provider_config(
            console, prov,
            state.get("llm_model") or "",
            state.get("llm_base_url") or "",
        )
        if not ok_prov:
            return False, err_prov, None
        console.print("[green]✓ Proveedor listo.[/]")
        return True, "", None

    if section_id == "summary":
        console.print(Panel("Resumen", title="Resumen", border_style="yellow"))
        t = Table(title="Resumen de configuración")
        t.add_column("Clave", style="yellow")
        t.add_column("Valor", style="white")
        t.add_row("Canal", state.get("channel", ""))
        t.add_row("Modo del bot", state.get("bot_mode", ""))
        if state.get("bot_mode") == "langgraph":
            t.add_row("Proveedor LLM", state.get("llm_provider") or "none_llm")
            if state.get("llm_model"):
                t.add_row("Modelo", state.get("llm_model"))
        t.add_row("Token (censurado)", _censor_token(state.get("token", "")))
        t.add_row("DB path", state.get("db_path", ""))
        if state.get("bot_mode") == "langgraph":
            save_tr = state.get("save_grpo_traces", False)
            if isinstance(save_tr, str):
                save_tr = str(save_tr).lower() in ("true", "1", "yes", "y", "sí", "si")
            t.add_row("Guardar trazas GRPO", "sí" if save_tr else "no")
            if save_tr:
                send_ls = state.get("send_to_langsmith", False)
                if isinstance(send_ls, str):
                    send_ls = str(send_ls).lower() in ("true", "1", "yes", "y", "sí", "si")
                t.add_row("Subir a LangSmith", "sí" if send_ls else "no")
        save_conv = state.get("save_conversation_traces", True)
        if isinstance(save_conv, str):
            save_conv = str(save_conv).lower() in ("true", "1", "yes", "y", "sí", "si")
        t.add_row("Guardar trazas de conversaciones", "sí" if save_conv else "no")
        if save_conv:
            t.add_row("Formato trazas", state.get("conversation_traces_format", "sft").upper())
        t.add_row("Modo setup", state.get("mode", ""))
        console.print(t)
        return True, "", None

    if section_id == "save_launch":
        _load_dotenv()
        if not state.get("token"):
            state["token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

        # ── Edición de servicio (salto desde welcome) ──────────────────────
        if state.get("_edit_service"):
            svc_name = state.pop("_edit_service_name", DEPLOY_SERVICE_NAME)
            svc_provider = state.pop("_edit_service_provider", "pm2")
            state.pop("_edit_service", None)
            _edit_service_settings(console, state, repo_root, svc_name, provider=svc_provider)
            run_now, nav = _confirm_with_nav(console, "¿Arrancar el bot ahora?", default=False)
            if nav is not None:
                return True, "", nav
            if not run_now:
                console.print("[dim]Configuración guardada. Ejecuta el bot cuando quieras.[/]")
                return True, "", None
            # Continúa hacia el lanzamiento directo (cae al final de save_launch)

        console.print(Panel("Guardar y lanzar", title="Finalizar", border_style="green"))
        if not state.get("_used_preferences_skip"):
            if Confirm.ask("¿Guardar esta configuración para la próxima vez?", default=True):
                db_path_save = _resolve_db_path_prefer_existing(
                    str(state.get("db_path", "telegram.duckdb")),
                    repo_root,
                    console,
                )
                if not _valid_db_path(db_path_save):
                    db_path_save = "db/telegram.duckdb"
                state["db_path"] = db_path_save
                save_tr = state.get("save_grpo_traces", False)
                if isinstance(save_tr, str):
                    save_tr = str(save_tr).lower() in ("true", "1", "yes", "y", "sí", "si")
                send_ls = state.get("send_to_langsmith", False)
                if isinstance(send_ls, str):
                    send_ls = str(send_ls).lower() in ("true", "1", "yes", "y", "sí", "si")
                save_conv = state.get("save_conversation_traces", True)
                if isinstance(save_conv, str):
                    save_conv = str(save_conv).lower() in ("true", "1", "yes", "y", "sí", "si")
                fmt_traces = (state.get("conversation_traces_format", "sft") or "sft").strip().lower()
                if fmt_traces not in ("grpo", "sft"):
                    fmt_traces = "sft"
                save_config(
                    mode=state.get("mode", "quick"),
                    channel=state.get("channel", "telegram"),
                    bot_mode=state.get("bot_mode", "echo"),
                    db_path=db_path_save,
                    llm_provider=state.get("llm_provider", ""),
                    llm_model=state.get("llm_model", ""),
                    llm_base_url=state.get("llm_base_url", ""),
                    save_grpo_traces=save_tr,
                    send_to_langsmith=send_ls,
                    save_conversation_traces=save_conv,
                    conversation_traces_format=fmt_traces,
                )
                _write_env_file(repo_root, "DUCKCLAW_DB_PATH", db_path_save)
                _write_env_file(repo_root, "DUCKCLAW_SAVE_CONVERSATION_TRACES", "true" if save_conv else "false")
                _write_env_file(repo_root, "DUCKCLAW_CONVERSATION_TRACES_FORMAT", fmt_traces)
                _ensure_db_file_exists(repo_root, db_path_save, console)
        state.pop("_used_preferences_skip", None)
        console.print()
        available_providers = _detect_available_deploy_providers()
        state["available_deploy_providers"] = available_providers
        _save_available_deploy_providers(available_providers)
        service_exists, existing_provider = _is_deploy_service_running(DEPLOY_SERVICE_NAME)
        if service_exists:
            console.print(f"[green]{DEPLOY_SERVICE_NAME}[/] ya está desplegado ({existing_provider}). Se omite la configuración de despliegue.")
            deploy_yes = False
            deploy_provider = existing_provider
        else:
            if available_providers:
                console.print(f"[dim]Servicios de persistencia detectados en este equipo: {', '.join(available_providers)}.[/]")
            else:
                console.print("[dim]No se detectó ningún servicio de persistencia (pm2, systemd, etc.).[/]")
            console.print()
            console.print(Panel("Opciones de servicio de persistencia (duckops)", title="Desplegar como servicio", border_style="blue"))
            t = Table(show_header=True, header_style="bold magenta")
            t.add_column("Proveedor", style="bold cyan")
            t.add_column("Descripción", style="white")
            t.add_row("pm2", "Node/PM2 (macOS, Linux); reinicio automático")
            t.add_row("systemd", "Systemd (Linux); unidad .service")
            t.add_row("windows", "Programador de tareas (Windows); al iniciar sesión o al arranque")
            t.add_row("cron", "Cron (pendiente de implementación)")
            t.add_row("auto", "Detecta el SO y elige pm2 (macOS) o systemd (Linux)")
            console.print(t)
            console.print("[dim]Si despliegas, el bot quedará registrado como servicio y se reiniciará solo.[/]")
            console.print(
                f"[dim]El proceso del bot es [bold]{DEPLOY_SERVICE_NAME}[/] (Telegram); "
                "el API Gateway es otro servicio PM2 distinto (p. ej. {GATEWAY_SERVICE_NAME}) "
                "y se ofrece configurar justo después del despliegue si hay PM2.[/]"
            )
            console.print()
            deploy_yes, nav = _confirm_with_nav(console, "¿Desplegar bot como servicio persistente con duckops?", default=False)
            if nav is not None:
                return True, "", nav
            deploy_provider = None
        if deploy_yes:
            default_provider = state.get("last_deploy_provider") or "auto"
            deploy_provider = (Prompt.ask("Proveedor de persistencia", default=default_provider) or "").strip().lower() or "auto"
            if deploy_provider not in DEPLOY_PROVIDERS:
                deploy_provider = "auto"
            _save_last_deploy_provider(deploy_provider)
            try:
                from duckclaw.ops.manager import deploy
                msg = deploy(
                    name=DEPLOY_SERVICE_NAME,
                    provider=deploy_provider,
                    command="-m duckclaw.graphs.telegram_bot",
                    cwd=str(repo_root),
                )
                console.print(Panel(msg, title="duckops deploy", border_style="blue"))
                # Si se usó auto, detectar el verdadero provider de deploy para generar la unidad
                actual_deploy_provider = deploy_provider
                if actual_deploy_provider == "auto":
                    system = platform.system()
                    if system == "Windows":
                        actual_deploy_provider = "windows"
                    elif system == "Linux":
                        actual_deploy_provider = "systemd"
                    else:
                        actual_deploy_provider = "pm2"

                if actual_deploy_provider == "systemd":
                    from duckclaw.ops.providers.systemd import get_systemd_unit_content
                    content, unit_name = get_systemd_unit_content(
                        name=DEPLOY_SERVICE_NAME,
                        command="-m duckclaw.graphs.telegram_bot",
                        python_path=os.path.abspath(sys.executable),
                        cwd=str(repo_root),
                    )
                    unit_path = repo_root / unit_name
                    unit_path.write_text(content + "\n", encoding="utf-8")
                    console.print(f"[green]Unidad guardada en:[/] [bold]{unit_path}[/]")
                    console.print("[dim]Instala con: sudo cp ... /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now DuckClaw-Brain[/]")
                if "Error" in msg or "not implemented" in msg.lower():
                    console.print("[yellow]El despliegue falló. Puedes arrancar el bot manualmente después.[/]")
            except Exception as e:
                console.print(f"[red]Error al desplegar el servicio o generar la unidad systemd: {e}[/]")
                console.print("[yellow]Módulo duckclaw.ops no disponible. Instala el paquete y vuelve a intentar.[/]")
        llm_is_mlx = (state.get("llm_provider") or "").strip().lower() == "mlx"
        start_mlx = repo_root / "duckclaw" / "mlx" / "start_mlx.sh"
        if not start_mlx.is_file():
            start_mlx = repo_root / "mlx" / "start_mlx.sh"
        if llm_is_mlx and start_mlx.is_file():
            use_pm2_inference = deploy_provider == "pm2" or (
                deploy_provider == "auto" and platform.system() != "Windows"
            )
            if use_pm2_inference and shutil.which("pm2"):
                msg = _ensure_pm2_inference_service(start_mlx, repo_root)
                console.print(Panel(msg, title=f"Servicio {INFERENCE_SERVICE_NAME} (MLX)", border_style="blue"))
            else:
                try:
                    subprocess.Popen(
                        [str(start_mlx)],
                        cwd=str(repo_root),
                        start_new_session=True,
                    )
                    console.print("[dim]Ejecutando duckclaw/mlx/start_mlx.sh en segundo plano.[/]")
                except Exception as e:
                    console.print(f"[yellow]No se pudo ejecutar duckclaw/mlx/start_mlx.sh: {e}[/]")
        # API Gateway (PM2): ofrecer aquí si hay PM2 y el bot ya estaba o acaba de desplegarse (antes de "arrancar ahora").
        # Así no depende de responder "no" a arrancar el bot ni de terminar el polling en primer plano.
        if shutil.which("pm2") and (service_exists or deploy_yes):
            _offer_gateway_pm2_if_pm2(console, state, repo_root)
        if service_exists:
            console.print("[dim]Configuración guardada. El bot ya está en marcha con el servicio; no se arranca otra instancia.[/]")
            return True, "", None
        default_run_now = not deploy_yes
        if deploy_yes:
            console.print("[dim]El bot ya está en marcha con el servicio (PM2/systemd/etc.). No arranques otra instancia aquí o habrá conflicto.[/]")
        run_now, nav = _confirm_with_nav(console, "¿Arrancar el bot de Telegram ahora?", default=default_run_now)
        if nav is not None:
            return True, "", nav
        if not run_now:
            console.print("[dim]Configuración guardada. Ejecuta el script del bot cuando quieras.[/]")
            return True, "", None
        if not state.get("token"):
            state["token"] = (Prompt.ask("TELEGRAM_BOT_TOKEN (obligatorio para arrancar)", password=True) or "").strip()
        if not state.get("token"):
            return False, "Falta TELEGRAM_BOT_TOKEN. Ponlo en .env o ejecuta de nuevo y escríbelo.", None
        env = os.environ.copy()
        env["TELEGRAM_BOT_TOKEN"] = state.get("token", "")
        env["DUCKCLAW_DB_PATH"] = state.get("db_path", "telegram.duckdb") if _valid_db_path(state.get("db_path")) else "telegram.duckdb"
        env["DUCKCLAW_BOT_MODE"] = state.get("bot_mode", "echo")
        if state.get("bot_mode") == "langgraph":
            env["DUCKCLAW_LLM_PROVIDER"] = state.get("llm_provider") or "none_llm"
            env["DUCKCLAW_LLM_MODEL"] = state.get("llm_model", "")
            env["DUCKCLAW_LLM_BASE_URL"] = state.get("llm_base_url", "")
            save_tr = state.get("save_grpo_traces", False)
            if isinstance(save_tr, str):
                save_tr = str(save_tr).lower() in ("true", "1", "yes", "y", "sí", "si")
            if save_tr:
                env["DUCKCLAW_SAVE_GRPO_TRACES"] = "true"
                send_ls = state.get("send_to_langsmith", False)
                if isinstance(send_ls, str):
                    send_ls = str(send_ls).lower() in ("true", "1", "yes", "y", "sí", "si")
                if send_ls:
                    env["DUCKCLAW_SEND_TO_LANGSMITH"] = "true"
        console.print(Panel("Arrancando bot en modo polling...", border_style="cyan"))
        env["PYTHONPATH"] = str(repo_root) + (
            os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else ""
        )
        try:
            ret = subprocess.call(
                [sys.executable, "-m", "duckclaw.graphs.telegram_bot"],
                cwd=str(repo_root),
                env=env,
            )
        except KeyboardInterrupt:
            console.print("\n[dim]Bot detenido por el usuario (Ctrl+C).[/]")
            sys.exit(130)
        if ret != 0:
            return False, "El bot terminó con error. Revisa los logs.", None
        return True, "", None

    return True, "", None


def main() -> int:
    # Limitar ancho para evitar duplicación de bordes en terminales muy anchos (ej. Cursor IDE)
    try:
        import shutil
        w = min(120, shutil.get_terminal_size().columns)
    except Exception:
        w = 100
    console = Console(width=w)
    # Raíz del monorepo (scripts/ -> parent)
    repo_root = Path(__file__).resolve().parent.parent
    bot_script = repo_root / "packages" / "agents" / "src" / "duckclaw" / "agents" / "telegram_bot.py"

    try:
      return _main_inner(console, repo_root, bot_script)
    except KeyboardInterrupt:
        console.print("\n[dim]Interrumpido (Ctrl+C).[/]")
        return 130


def _main_inner(console: Console, repo_root: Path, bot_script: Path) -> int:
    _load_dotenv()
    if "--resolve-gateways" in sys.argv:
        _wizard_resolve_gateway_conflicts(console, repo_root)
        return 0
    # ── PASO 0: Detectar servicio de persistencia (SIEMPRE lo primero) ───
    console.print(Panel("[bold green]DuckClaw 🦆⚔️[/]", border_style="green"))

    has_systemd = False
    is_user_systemd = False
    systemd_status = "no registrado"
    if platform.system() == "Linux" and shutil.which("systemctl"):
        unit = DEPLOY_SERVICE_NAME.lower().replace(" ", "-") + ".service"
        # Check user service (exists if returncode != 4)
        r_user = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True, timeout=3)
        if r_user.returncode != 4:
            has_systemd = True
            is_user_systemd = True
            systemd_status = r_user.stdout.strip()
        else:
            # Check system service
            r_sys = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=3)
            if r_sys.returncode != 4:
                has_systemd = True
                systemd_status = r_sys.stdout.strip()

    if has_systemd:
        t = Table(title="Servicio Systemd detectado", border_style="cyan")
        t.add_column("Nombre", style="bold cyan")
        t.add_column("Estado", style="white")
        t.add_column("Tipo", style="dim")
        color = _status_style("online" if systemd_status == "active" else systemd_status)
        t.add_row(DEPLOY_SERVICE_NAME, f"[{color}]{systemd_status}[/]", "usuario" if is_user_systemd else "sistema")
        console.print(t)

        console.print(Panel(
            "Se detectó un servicio Systemd de DuckClaw. Puedes gestionar o configurar\n"
            "sus variables de entorno sin pasar por la configuración completa.",
            title="Servicio de persistencia",
            border_style="cyan",
        ))
        edit_svc, _ = _confirm_with_nav(
            console,
            "¿Gestionar servicio Systemd (omitir configuración completa)?",
            default=False,
        )
        if edit_svc:
            saved_for_edit = load_config() or {}
            svc_state: dict[str, Any] = {}
            for k in CONFIG_KEYS:
                if k in saved_for_edit:
                    svc_state[k] = saved_for_edit[k]
            svc_state["token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            _edit_service_settings(console, svc_state, repo_root, DEPLOY_SERVICE_NAME, provider="systemd")
            return 0

    elif shutil.which("pm2") is not None:
        # Buscar cualquier proceso PM2 registrado (no solo nombres conocidos)
        pm2_procs: list[dict[str, Any]] = []
        try:
            r = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                import json as _json
                pm2_procs = _json.loads(r.stdout or "[]")
                if not isinstance(pm2_procs, list):
                    pm2_procs = []
        except Exception:
            pm2_procs = []

        # Mostrar tabla de procesos detectados
        if pm2_procs:
            t = Table(title="Servicios PM2 detectados", border_style="cyan")
            t.add_column("Nombre", style="bold cyan")
            t.add_column("Estado", style="white")
            t.add_column("Reinicios", style="dim")
            for p in pm2_procs:
                name = p.get("name", "?")
                status = (p.get("pm2_env") or {}).get("status", "?")
                restarts = str((p.get("pm2_env") or {}).get("restart_time", "-"))
                color = _status_style(status)
                t.add_row(name, f"[{color}]{status}[/]", restarts)
            console.print(t)
        else:
            console.print("[dim]PM2 disponible. No hay procesos registrados aún.[/]")

        console.print(Panel(
            "Se detectó PM2. Puedes editar un servicio del pipeline (spec FLUJO_VIDA_DATO) o continuar con la configuración completa.\n"
            "[dim]Si eliges la opción 0, al final del asistente se ofrecerá configurar el API Gateway "
            "(nombre PM2 personalizado, BD, Redis) si lo necesitas.[/]",
            title="Servicio de persistencia",
            border_style="cyan",
        ))
        # Menú: 0 = config completa, r = conflictos gateways, 1..N = editar proceso
        found_svc: str | None = None
        gw_json_menu = repo_root / "config" / "api_gateways_pm2.json"
        if pm2_procs:
            names = [p.get("name", "") for p in pm2_procs if p.get("name")]
            name_table = Table(show_header=False, box=None)
            name_table.add_row("0", "Continuar con configuración completa (no editar)")
            name_table.add_row(
                "r",
                "Resolver conflictos API Gateway (puerto / DuckDB / lsof)",
            )
            for i, n in enumerate(names, 1):
                name_table.add_row(str(i), n)
            console.print(name_table)
            default_idx = 1
            saved_gw = (load_config() or {}).get("gateway_pm2_name")
            saved_gw = (str(saved_gw).strip() if saved_gw else "") or GATEWAY_SERVICE_NAME
            if saved_gw in names:
                default_idx = names.index(saved_gw) + 1
            elif GATEWAY_SERVICE_NAME in names:
                default_idx = names.index(GATEWAY_SERVICE_NAME) + 1
            choice = Prompt.ask(
                "Selecciona [0=config completa, r=conflictos gateways]",
                choices=[str(i) for i in range(0, len(names) + 1)] + ["r"],
                default=str(default_idx),
            )
            if choice == "r":
                _wizard_resolve_gateway_conflicts(console, repo_root)
                return 0
            idx = int(choice)
            if idx == 0:
                found_svc = None  # continuar con configuración completa
            else:
                found_svc = names[idx - 1]
        else:
            # Sin procesos PM2: aún se puede corregir api_gateways_pm2.json si existe
            if gw_json_menu.is_file():
                name_table = Table(show_header=False, box=None)
                name_table.add_row("0", "Continuar con configuración completa (no editar)")
                name_table.add_row(
                    "r",
                    "Resolver conflictos API Gateway (puerto / DuckDB / lsof)",
                )
                console.print(name_table)
                choice = Prompt.ask(
                    "Selecciona [0=config completa, r=conflictos gateways]",
                    choices=["0", "r"],
                    default="0",
                )
                if choice == "r":
                    _wizard_resolve_gateway_conflicts(console, repo_root)
                    return 0
            found_svc = None
        if found_svc is not None:
            saved_for_edit = load_config() or {}
            svc_state: dict[str, Any] = {}
            for k in CONFIG_KEYS:
                if k in saved_for_edit:
                    svc_state[k] = saved_for_edit[k]
            svc_state.setdefault("gateway_pm2_name", GATEWAY_SERVICE_NAME)
            svc_state["token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            _edit_service_settings(console, svc_state, repo_root, found_svc, provider="pm2")
            return 0

    # ── PASO 1: Cargar configuración guardada ─────────────────────────────
    state: dict[str, Any] = {}
    saved = load_config()
    if saved:
        state["_from_saved"] = True
        for k in CONFIG_KEYS:
            if k in saved:
                state[k] = saved[k]
        if (state.get("llm_provider") or "").strip().lower() == "custom":
            state["llm_provider"] = "mlx"
    state.setdefault("mode", "quick")
    state.setdefault("channel", "telegram")
    state.setdefault("bot_mode", "echo")
    state.setdefault("db_path", "telegram.duckdb")
    state.setdefault("llm_provider", "")
    state.setdefault("llm_model", "")
    state.setdefault("llm_base_url", "")
    state.setdefault("save_grpo_traces", True)
    state.setdefault("save_conversation_traces", True)
    state.setdefault("conversation_traces_format", "sft")
    state.setdefault("gateway_pm2_name", GATEWAY_SERVICE_NAME)
    state.setdefault("send_to_langsmith", True)
    idx = 0

    while True:
        section_id = SECTION_IDS[idx]
        if section_id == "provider" and state.get("bot_mode") != "langgraph":
            idx = _next_index(idx, state) or idx
            continue
        if section_id == "grpo_traces" and state.get("bot_mode") != "langgraph":
            idx = _next_index(idx, state) or idx
            continue
        if section_id == "validate_provider" and state.get("bot_mode") != "langgraph":
            idx = _next_index(idx, state) or idx
            continue

        num, total = _section_progress(idx, state)
        titles = {
            "welcome": "",
            "mode": "Modo",
            "channel": "Canal",
            "bot_mode": "Modo del bot",
            "provider": "Model provider",
            "deps": "Dependencias",
            "token": "Token",
            "db_path": "DB",
            "grpo_traces": "Trazas GRPO",
            "conversation_traces": "Trazas de conversaciones",
            "validate_provider": "Validar proveedor",
            "summary": "Resumen",
            "save_launch": "Finalizar",
        }
        console.print(f"[bold cyan]Sección {num}/{total}: {titles.get(section_id, section_id)}[/]")
        console.print()
        ok, err, nav = _run_section(section_id, console, state, repo_root, bot_script)
        if not ok:
            console.print(Panel(err, title="❌ Error", border_style="red"))

        if section_id == "welcome":
            if state.get("_skip_to_summary"):
                idx = SECTION_IDS.index("summary")
                state.pop("_skip_to_summary", None)
            else:
                idx = _next_index(idx, state) or idx
            continue

        if nav == NAV_QUIT:
            if Confirm.ask("¿Salir sin arrancar el bot?", default=False):
                return 0
            continue
        if nav == NAV_PREV:
            idx = _prev_index(idx, state)
            continue
        next_i = _next_index(idx, state)
        if next_i is None:
            break
        idx = next_i

    return 0


if __name__ == "__main__":
    sys.exit(main())

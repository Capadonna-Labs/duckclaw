#!/usr/bin/env python3
"""DuckClaw setup wizard: interactive install and Telegram bootstrap with Rich."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

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

CONFIG_KEYS = ("mode", "channel", "bot_mode", "llm_provider", "llm_model", "llm_base_url", "db_path")
DEPLOY_PROVIDERS = ("auto", "pm2", "systemd", "windows", "cron")
DEPLOY_SERVICE_NAME = "DuckClaw-Brain"
INFERENCE_SERVICE_NAME = "DuckClaw-Inference"
# Orden: IoTCoreLabs, OpenAI, Anthropic, MLX (principales); luego Ollama y none_llm
LLM_PROVIDERS = ("iotcorelabs", "openai", "anthropic", "mlx", "ollama", "none_llm")
TELEGRAM_TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
API_VALIDATION_TIMEOUT = 8

# Bienvenida → Canal → Modo del bot → Proveedor → … (provider/validate_provider se saltan si bot_mode != "langgraph")
SECTION_IDS = (
    "welcome",
    "channel",
    "bot_mode",
    "provider",
    "mode",
    "deps",
    "token",
    "db_path",
    "validate_provider",
    "summary",
    "save_launch",
)


def _config_path() -> Path:
    return Path.home() / ".config" / "duckclaw" / "wizard_config.json"


def _load_dotenv() -> None:
    """Carga .env en os.environ si existe (busca en cwd y en la raíz del repo)."""
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent):
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
                out["db_path"] = v if _valid_db_path(v) else "telegram.duckdb"
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


def save_config(
    mode: str,
    channel: str,
    bot_mode: str,
    db_path: str,
    llm_provider: str = "",
    llm_model: str = "",
    llm_base_url: str = "",
) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "mode": mode,
        "channel": channel,
        "bot_mode": bot_mode,
        "db_path": db_path,
        "llm_provider": llm_provider or "",
        "llm_model": llm_model or "",
        "llm_base_url": llm_base_url or "",
    }
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
                "DuckClaw no está disponible.\nInstala: pip install -e . --no-build-isolation",
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
                "Falta el extra de Telegram.\nInstala: pip install -e \".[telegram]\" --no-build-isolation",
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
    provider_table = Table(title="Model provider (elige: Anthropic, OpenAI, MLX, IoTCoreLabs)", border_style="cyan")
    provider_table.add_column("Opción", style="bold cyan")
    provider_table.add_column("Descripción", style="white")
    for p in LLM_PROVIDERS:
        desc = {
            "iotcorelabs": "IoTCoreLabs",
            "openai": "OpenAI API",
            "anthropic": "Anthropic API",
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
        console.print(
            Panel(
                "[bold green]DuckClaw 🦆⚔️[/]\n[dim]s = siguiente · a = anterior · q = salir[/]",
                border_style="green",
            )
        )
        if state.get("_from_saved"):
            console.print(f"[dim]Preferencias cargadas desde {_config_path()}.[/]")
            if Confirm.ask("¿Usar estas preferencias y saltar al resumen?", default=True):
                state["_skip_to_summary"] = True
                state["_used_preferences_skip"] = True
                _load_dotenv()
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
        console.print(Panel("Token (no se guarda)", title="Token", border_style="cyan"))
        _load_dotenv()
        token_from_env = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if token_from_env:
            state["token"] = token_from_env
            console.print("[dim]Token tomado de .env o TELEGRAM_BOT_TOKEN.[/]")
        else:
            console.print("[dim]El token no se guarda por seguridad.[/]")
            val, nav = _prompt_with_nav(console, "TELEGRAM_BOT_TOKEN", password=True)
            if nav:
                return True, "", nav
            state["token"] = (val or "").strip()
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
        default_db = (
            os.environ.get("DUCKCLAW_DB_PATH")
            or (state.get("db_path") if _valid_db_path(state.get("db_path")) else None)
            or "telegram.duckdb"
        )
        val, nav = _prompt_with_nav(console, "DUCKCLAW_DB_PATH", default=default_db)
        if nav:
            return True, "", nav
        raw = (val or "").strip() or "telegram.duckdb"
        state["db_path"] = raw if _valid_db_path(raw) else "telegram.duckdb"
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
        t.add_row("Modo setup", state.get("mode", ""))
        console.print(t)
        return True, "", None

    if section_id == "save_launch":
        _load_dotenv()
        if not state.get("token"):
            state["token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        console.print(Panel("Guardar y lanzar", title="Finalizar", border_style="green"))
        if not state.get("_used_preferences_skip"):
            if Confirm.ask("¿Guardar esta configuración para la próxima vez?", default=True):
                db_path_save = state.get("db_path", "telegram.duckdb")
                if not _valid_db_path(db_path_save):
                    db_path_save = "telegram.duckdb"
                save_config(
                    mode=state.get("mode", "quick"),
                    channel=state.get("channel", "telegram"),
                    bot_mode=state.get("bot_mode", "echo"),
                    db_path=db_path_save,
                    llm_provider=state.get("llm_provider", ""),
                    llm_model=state.get("llm_model", ""),
                    llm_base_url=state.get("llm_base_url", ""),
                )
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
            console.print()
            deploy_yes, nav = _confirm_with_nav(console, "¿Desplegar bot como servicio persistente con duckops?", default=True)
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
                    command="-m duckclaw.agents.telegram_bot",
                    cwd=str(repo_root),
                )
                console.print(Panel(msg, title="duckops deploy", border_style="blue"))
                if "Error" in msg or "not implemented" in msg.lower():
                    console.print("[yellow]El despliegue falló. Puedes arrancar el bot manualmente después.[/]")
            except ImportError:
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
        console.print(Panel("Arrancando bot en modo polling...", border_style="cyan"))
        try:
            ret = subprocess.call(
                [sys.executable, "-m", "duckclaw.agents.telegram_bot"],
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
    console = Console()
    repo_root = Path(__file__).resolve().parent.parent
    bot_script = repo_root / "examples" / "telegram_bot.py"

    # Siempre revisar primero el JSON de preferencias; evita configurar todo desde 0
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
    idx = 0

    try:
        while True:
            section_id = SECTION_IDS[idx]
            if section_id == "provider" and state.get("bot_mode") != "langgraph":
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
    except KeyboardInterrupt:
        console.print("\n[dim]Interrumpido (Ctrl+C).[/]")
        return 130


if __name__ == "__main__":
    sys.exit(main())

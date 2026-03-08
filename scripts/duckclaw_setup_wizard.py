#!/usr/bin/env python3
"""DuckClaw setup wizard: interactive install and Telegram bootstrap with Rich."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
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

CONFIG_KEYS = (
    "mode",
    "channel",
    "bot_mode",
    "llm_provider",
    "llm_model",
    "llm_base_url",
    "db_path",
    "service_persistence",
)
LLM_PROVIDERS = ("iotcorelabs", "openai", "anthropic", "ollama", "none_llm", "mlx")
TELEGRAM_TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
API_VALIDATION_TIMEOUT = 8

# Bienvenida → Canal → Modo del bot → Proveedor → …
# provider/validate_provider solo aplican en modos con proveedor (langgraph/bicameral_langgraph)
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
    "pm2",
    "save_launch",
)

PM2_APP_NAME_DEFAULT = "Finanz-Inference"


def _print_section(console: Console, title: str, body: str = "", style: str = "cyan") -> None:
    """Render a consistent section header panel."""
    console.print(Panel(body, title=title, border_style=style, expand=False))


def _print_ok(console: Console, text: str) -> None:
    console.print(f"[green]✓ {text}[/]")


def _status_style(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "online":
        return "green"
    if s in ("stopped", "no registrado", "unknown"):
        return "yellow"
    return "red"


def _normalize_db_path(path: str) -> str:
    """Store relative DB paths under db/ by default."""
    p = (path or "").strip()
    if not p:
        return "db/telegram.duckdb"
    if p == ":memory:":
        return p
    if os.path.isabs(p):
        return p
    if p.startswith("db/"):
        return p
    return f"db/{p}"


def _show_pm2_section(state: dict[str, Any]) -> bool:
    """Return True when wizard should show PM2 management section."""
    return (state.get("service_persistence") or "setup_here") != "already_configured"


def _uses_provider_section(bot_mode: str) -> bool:
    """Return True when bot mode needs provider/model configuration."""
    return (bot_mode or "").strip().lower() in ("langgraph", "bicameral_langgraph")


def _config_path() -> Path:
    return Path.home() / ".config" / "core" / "wizard_config.json"


def load_config() -> dict[str, Any] | None:
    path = _config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return {k: data[k] for k in CONFIG_KEYS if k in data and data[k]}
    except Exception:
        return None


def save_config(
    mode: str,
    channel: str,
    bot_mode: str,
    db_path: str,
    llm_provider: str = "",
    llm_model: str = "",
    llm_base_url: str = "",
    service_persistence: str = "setup_here",
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
        "service_persistence": service_persistence or "setup_here",
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
        import core  # noqa: F401
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
    _print_ok(console, "Dependencias correctas.")
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
    _print_ok(console, "LangGraph disponible.")
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
            return False, "MLX requiere URL base del modelo (ej. http://127.0.0.1:8000/v1)."
        if not model.strip():
            return False, "MLX requiere nombre del modelo."
        return True, ""
    return False, f"Proveedor desconocido: {provider}"


def _ask_provider(console: Console, state: dict[str, Any]) -> str | None:
    """Devuelve nav (next/prev/quit) si el usuario escribe s/a/q en el primer prompt, o None."""
    provider_table = Table(title="Proveedor para bot inteligente", border_style="cyan")
    provider_table.add_column("Opción", style="bold cyan")
    provider_table.add_column("Descripción", style="white")
    for p in LLM_PROVIDERS:
        desc = {
            "openai": "OpenAI API",
            "anthropic": "Anthropic API",
            "ollama": "Ollama local",
            "none_llm": "Sin LLM (reglas + memoria DuckClaw)",
            "iotcorelabs": "IoTCoreLabs",
            "mlx": "MLX (servidor local OpenAI-compatible)",
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
            default_mlx_url = "http://127.0.0.1:8000/v1"
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


def _pm2_available() -> bool:
    """Check if pm2 is installed and runnable."""
    try:
        r = subprocess.run(
            ["pm2", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _pm2_jlist() -> list[dict[str, Any]] | None:
    """Run pm2 jlist and return parsed JSON, or None if unavailable."""
    try:
        r = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None


def _generate_ecosystem_config(repo_root: Path, state: dict[str, Any]) -> str:
    """Generate ecosystem.core.config.cjs content from wizard state."""
    app_name = os.environ.get("DUCKCLAW_PM2_APP_NAME", PM2_APP_NAME_DEFAULT)
    db_path = _normalize_db_path(state.get("db_path", "db/telegram.duckdb"))
    bot_mode = state.get("bot_mode", "langgraph")
    llm_provider = state.get("llm_provider", "none_llm")
    llm_model = state.get("llm_model", "")
    llm_base_url = state.get("llm_base_url", "")
    cwd = str(repo_root)
    venv_python = str(repo_root / ".venv" / "bin" / "python3")
    env_lines = [
        f'    PYTHONPATH: "{cwd}",',
        f'    DUCKCLAW_DB_PATH: "{db_path}",',
        f'    DUCKCLAW_BOT_MODE: "{bot_mode}",',
        f'    DUCKCLAW_LLM_PROVIDER: "{llm_provider}",',
        f'    DUCKCLAW_LLM_MODEL: "{llm_model}",',
        f'    DUCKCLAW_LLM_BASE_URL: "{llm_base_url}",',
    ]
    env_block = "\n".join(env_lines)
    return f'''/**
 * PM2 config for DuckClaw Telegram bot (generated by wizard).
 * Start: pm2 start ecosystem.core.config.cjs
 * Stop:  pm2 stop {app_name}
 *
 * Token: guardado en .env (auto-cargado por el bot al iniciar).
 * Para actualizar el token: edita .env o regenera este config desde el wizard.
 */
module.exports = {{
  apps: [
    {{
      name: "{app_name}",
      script: "{venv_python}",
      args: "-m core.integrations.telegram_bot",
      cwd: "{cwd}",
      interpreter: "none",
      autorestart: true,
      watch: false,
      max_restarts: 10,
      env: {{
        PYTHONPATH: "{cwd}",
        DUCKCLAW_DB_PATH: "{db_path}",
        DUCKCLAW_BOT_MODE: "{bot_mode}",
        DUCKCLAW_LLM_PROVIDER: "{llm_provider}",
        DUCKCLAW_LLM_MODEL: "{llm_model}",
        DUCKCLAW_LLM_BASE_URL: "{llm_base_url}",
      }},
    }},
  ],
}};
'''


def _write_env_token(token: str, repo_root: Path) -> None:
    """Write or update TELEGRAM_BOT_TOKEN in .env (project root). Never overwrites other keys."""
    env_path = repo_root / ".env"
    lines: list[str] = []
    found = False
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                lines.append(f'TELEGRAM_BOT_TOKEN="{token}"')
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f'TELEGRAM_BOT_TOKEN="{token}"')
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_dotenv_value(repo_root: Path, key: str) -> str:
    """Read a single value from .env without side effects."""
    env_path = repo_root / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return ""


def _configure_pm2_settings(
    console: Console,
    state: dict[str, Any],
) -> None:
    """Interactive sub-menu to edit key service settings stored in state."""
    _print_section(
        console,
        "Configurar servicio",
        "Edita los parámetros del servicio antes de generar el config de PM2.",
        "cyan",
    )

    # App name
    current_name = os.environ.get("DUCKCLAW_PM2_APP_NAME", PM2_APP_NAME_DEFAULT)
    new_name = Prompt.ask("Nombre de la app PM2", default=current_name).strip()
    if new_name:
        os.environ["DUCKCLAW_PM2_APP_NAME"] = new_name

    # Bot mode
    modes_table = Table(title="Modos disponibles", show_header=False, box=None)
    modes_table.add_column("Opción", style="bold cyan", width=4)
    modes_table.add_column("Descripción")
    modes_table.add_row("1", "echo      – respuesta eco simple")
    modes_table.add_row("2", "langgraph – LangGraph + memoria bicameral (recomendado)")
    console.print(modes_table)
    current_mode = state.get("bot_mode", "langgraph")
    mode_map = {"1": "echo", "2": "langgraph"}
    mode_default = "1" if current_mode == "echo" else "2"
    mode_choice = Prompt.ask("Modo del bot", choices=["1", "2"], default=mode_default).strip()
    state["bot_mode"] = mode_map.get(mode_choice, "langgraph")

    # DB path
    current_db = _normalize_db_path(state.get("db_path", "db/telegram.duckdb"))
    new_db = Prompt.ask("Ruta de la base de datos (DuckDB)", default=current_db).strip()
    state["db_path"] = _normalize_db_path(new_db) if new_db else current_db

    # Token (opcional — puede dejarse en blanco para usar el de entorno)
    current_token = state.get("token", "")
    console.print(
        "[dim]Token de Telegram. Déjalo en blanco para usar la variable de entorno "
        "TELEGRAM_BOT_TOKEN.[/]"
    )
    new_token = Prompt.ask(
        "Token de Telegram",
        default=_censor_token(current_token) if current_token else "",
        password=False,
    ).strip()
    # Only update if it looks like a real token (not a censored placeholder)
    if new_token and not new_token.endswith("…") and "***" not in new_token:
        state["token"] = new_token
        _write_env_token(new_token, repo_root=Path(__file__).resolve().parent.parent)

    # LLM settings (solo si el modo lo requiere)
    if _uses_provider_section(state.get("bot_mode", "")):
        providers_table = Table(title="Proveedores LLM", show_header=False, box=None)
        for p in LLM_PROVIDERS:
            providers_table.add_row(f"  {p}")
        console.print(providers_table)
        current_prov = state.get("llm_provider", "none_llm")
        new_prov = Prompt.ask("Proveedor LLM", default=current_prov or "none_llm").strip().lower()
        state["llm_provider"] = new_prov or "none_llm"

        current_model = state.get("llm_model", "")
        new_model = Prompt.ask("Modelo LLM (opcional)", default=current_model or "").strip()
        state["llm_model"] = new_model

        current_url = state.get("llm_base_url", "")
        new_url = Prompt.ask("URL base LLM (opcional)", default=current_url or "").strip()
        state["llm_base_url"] = new_url

    # ── Resumen tras editar ──────────────────────────────────────────────────
    app_name_final = os.environ.get("DUCKCLAW_PM2_APP_NAME", PM2_APP_NAME_DEFAULT)
    summary = Table(title="Resumen del servicio de persistencia", border_style="green")
    summary.add_column("Parámetro", style="bold green")
    summary.add_column("Valor", style="white")
    summary.add_row("App PM2", app_name_final)
    summary.add_row("Modo bot", state.get("bot_mode", "langgraph"))
    summary.add_row("DB path", _normalize_db_path(state.get("db_path", "db/telegram.duckdb")))
    summary.add_row("Token", _censor_token(state.get("token", "")) or "[dim](usa TELEGRAM_BOT_TOKEN)[/]")
    if _uses_provider_section(state.get("bot_mode", "")):
        summary.add_row("Proveedor LLM", state.get("llm_provider") or "none_llm")
        summary.add_row("Modelo LLM", state.get("llm_model") or "-")
        summary.add_row("URL base LLM", state.get("llm_base_url") or "-")
    console.print(summary)
    _print_ok(console, "Configuración actualizada.")


def _run_section_pm2(
    console: Console,
    state: dict[str, Any],
    repo_root: Path,
) -> tuple[bool, str, str | None]:
    """PM2 management section: configure settings, generate config, restart, start, stop."""
    app_name = os.environ.get("DUCKCLAW_PM2_APP_NAME", PM2_APP_NAME_DEFAULT)
    if not _pm2_available():
        console.print(
            Panel(
                "PM2 no está instalado o no está en PATH. "
                "Instala con: npm install -g pm2",
                title="PM2 no disponible",
                border_style="yellow",
            )
        )
        return True, "", None

    processes = _pm2_jlist()
    app = next((p for p in (processes or []) if p.get("name") == app_name), None)
    status = (app.get("pm2_env") or {}).get("status", "unknown") if app else "no registrado"
    status_color = _status_style(status)

    _print_section(
        console,
        "PM2",
        f"Administra el servicio [bold]{app_name}[/] (estado: [{status_color}]{status}[/{status_color}]).",
        "cyan",
    )

    # Show current key settings
    settings_table = Table(title="Configuración actual del servicio", border_style="dim")
    settings_table.add_column("Parámetro", style="dim cyan")
    settings_table.add_column("Valor", style="white")
    settings_table.add_row("App PM2", app_name)
    settings_table.add_row("Modo bot", state.get("bot_mode", "langgraph"))
    settings_table.add_row("DB path", _normalize_db_path(state.get("db_path", "db/telegram.duckdb")))
    if _uses_provider_section(state.get("bot_mode", "")):
        settings_table.add_row("Proveedor LLM", state.get("llm_provider") or "none_llm")
        settings_table.add_row("Modelo LLM", state.get("llm_model") or "-")
    settings_table.add_row("Token", _censor_token(state.get("token", "")))
    console.print(settings_table)

    t = Table(title=f"Acciones PM2: {app_name}")
    t.add_column("Opción", style="bold cyan")
    t.add_column("Descripción", style="white")
    t.add_row("0", "Editar configuración del servicio (nombre, modo, DB, token, LLM…)")
    t.add_row("1", "Generar/actualizar ecosystem.core.config.cjs")
    t.add_row("2", "Reiniciar servicio")
    t.add_row("3", "Iniciar servicio")
    t.add_row("4", "Detener servicio")
    t.add_row("s", "Siguiente (omitir)")
    console.print(t)

    val, nav = _prompt_with_nav(
        console, "Acción PM2",
        choices=["0", "1", "2", "3", "4", "s"],
        default="s",
    )
    if nav:
        return True, "", nav

    choice = (val or "s").strip().lower()

    if choice == "0":
        _configure_pm2_settings(console, state)
        # Re-enter the menu after editing so the user can generate/apply the new config
        return _run_section_pm2(console, state, repo_root)

    if choice == "1":
        config_path = repo_root / "ecosystem.core.config.cjs"
        content = _generate_ecosystem_config(repo_root, state)
        config_path.write_text(content, encoding="utf-8")
        _print_ok(console, f"Config generado: {config_path}")
        console.print(
            "[dim]Exporta TELEGRAM_BOT_TOKEN y ejecuta: pm2 start ecosystem.core.config.cjs[/]"
        )
        return True, "", None

    if choice == "2":
        return _run_pm2_cmd(console, ["pm2", "restart", app_name], "Reiniciando...")

    if choice == "3":
        config_path = repo_root / "ecosystem.core.config.cjs"
        if not config_path.exists():
            content = _generate_ecosystem_config(repo_root, state)
            config_path.write_text(content, encoding="utf-8")
            console.print(f"[dim]Config generado: {config_path}[/]")
        return _run_pm2_cmd(
            console,
            ["pm2", "start", str(config_path)],
            "Iniciando...",
        )

    if choice == "4":
        return _run_pm2_cmd(console, ["pm2", "stop", app_name], "Deteniendo...")

    return True, "", None


def _run_pm2_cmd(
    console: Console,
    cmd: list[str],
    status_msg: str,
) -> tuple[bool, str, str | None]:
    """Run a pm2 command and return (success, error_msg, nav)."""
    try:
        with console.status(status_msg, spinner="dots"):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return False, r.stderr or r.stdout or f"pm2 exit code {r.returncode}", None
        _print_ok(console, "Comando ejecutado.")
        out = (r.stdout or "").strip()
        if out:
            snippet = "\n".join(out.splitlines()[-6:])
            console.print(Panel(snippet, title="Salida PM2", border_style="green", expand=False))
        return True, "", None
    except subprocess.TimeoutExpired:
        return False, "Timeout ejecutando pm2.", None
    except Exception as e:
        return False, str(e), None


def _next_index(i: int, state: dict[str, Any]) -> int | None:
    """None = fin (ejecutar lanzamiento)."""
    if i >= len(SECTION_IDS) - 1:
        return None
    n = i + 1
    # Si ya hay servicio de persistencia, saltar todo lo que no sea save_launch
    if state.get("service_persistence") == "already_configured":
        save_launch_idx = SECTION_IDS.index("save_launch")
        if n < save_launch_idx:
            return save_launch_idx
    # Saltar provider si el modo no usa proveedor
    if n < len(SECTION_IDS) and SECTION_IDS[n] == "provider" and not _uses_provider_section(state.get("bot_mode", "")):
        n += 1
    # Saltar validate_provider si el modo no usa proveedor
    if n < len(SECTION_IDS) and SECTION_IDS[n] == "validate_provider" and not _uses_provider_section(state.get("bot_mode", "")):
        n += 1
    # Saltar PM2 si el usuario ya tiene servicio de persistencia configurado
    if n < len(SECTION_IDS) and SECTION_IDS[n] == "pm2" and not _show_pm2_section(state):
        n += 1
    if n >= len(SECTION_IDS):
        return None
    return n


def _prev_index(i: int, state: dict[str, Any]) -> int:
    if i <= 0:
        return 0
    p = i - 1
    if SECTION_IDS[p] == "validate_provider" and not _uses_provider_section(state.get("bot_mode", "")):
        p -= 1
    if SECTION_IDS[p] == "provider" and not _uses_provider_section(state.get("bot_mode", "")):
        p -= 1
    if p >= 0 and SECTION_IDS[p] == "pm2" and not _show_pm2_section(state):
        p -= 1
    return max(0, p)


def _section_progress(idx: int, state: dict[str, Any]) -> tuple[int, int]:
    """(número actual 1-based, total) considerando secciones saltadas."""
    order: list[int] = []
    for i in range(len(SECTION_IDS)):
        sid = SECTION_IDS[i]
        if sid == "provider" and not _uses_provider_section(state.get("bot_mode", "")):
            continue
        if sid == "validate_provider" and not _uses_provider_section(state.get("bot_mode", "")):
            continue
        if sid == "pm2" and not _show_pm2_section(state):
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
        _print_section(
            console,
            "DuckClaw 🦆⚔️",
            "Asistente de configuración para Telegram + PM2.",
            "green",
        )

        if "mode" not in state:
            state["mode"] = "quick"
            state["channel"] = "telegram"
            state["bot_mode"] = "bicameral"
            state["llm_provider"] = ""
            state["llm_model"] = ""
            state["llm_base_url"] = ""
            state["db_path"] = "db/telegram.duckdb"
            state["service_persistence"] = "setup_here"

        _print_section(
            console,
            "Persistencia",
            "¿Ya tienes un servicio de persistencia para el bot (pm2, systemd, launchd, etc.)?",
            "cyan",
        )
        t = Table()
        t.add_column("Opción", style="bold cyan")
        t.add_column("Descripción", style="white")
        t.add_row("1", "Sí, ya lo tengo configurado (omitir PM2)")
        t.add_row("2", "No, quiero configurarlo desde este wizard (PM2)")
        console.print(t)
        default_persistence = state.get("service_persistence") or "setup_here"
        default_option = "1" if default_persistence == "already_configured" else "2"
        val, nav = _prompt_with_nav(
            console,
            "Servicio de persistencia",
            choices=["1", "2"],
            default=default_option,
        )
        if nav:
            return True, "", nav
        raw = (val or "").strip().lower()
        if raw == "1":
            state["service_persistence"] = "already_configured"
        elif raw == "2":
            state["service_persistence"] = "setup_here"
        else:
            state["service_persistence"] = default_persistence

        saved = load_config()
        if saved:
            state["_saved"] = saved
            content = "Usar configuración guardada como valores por defecto?"
            _print_section(console, "Configuración guardada", content, "green")
            raw = Prompt.ask("[y/n]", choices=["y", "n"], default="y")
            if (raw or "y").strip().lower() == "y":
                persistence_choice = state.get("service_persistence", "setup_here")
                state["mode"] = saved.get("mode") or "quick"
                state["channel"] = saved.get("channel") or "telegram"
                state["bot_mode"] = saved.get("bot_mode") or "bicameral"
                prov = (saved.get("llm_provider") or "").strip().lower()
                state["llm_provider"] = "mlx" if prov == "custom" else prov
                state["llm_model"] = (saved.get("llm_model") or "").strip()
                state["llm_base_url"] = (saved.get("llm_base_url") or "").strip()
                state["db_path"] = _normalize_db_path(saved.get("db_path") or "db/telegram.duckdb")
                # Respeta la decisión tomada en la pregunta inicial de persistencia.
                state["service_persistence"] = persistence_choice
                _print_ok(console, "Valores cargados.")
        else:
            state["_saved"] = {}
        return True, "", None

    if section_id == "mode":
        _print_section(console, "Modo", "Selecciona la experiencia del asistente.", "cyan")
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
        _print_section(console, "Canal", "Por ahora solo está disponible Telegram.", "cyan")
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
        _print_section(console, "Modo del bot", "Define si responde con memoria bicameral, eco o LangGraph.", "cyan")
        t = Table()
        t.add_column("Opción", style="bold cyan")
        t.add_column("Descripción", style="white")
        t.add_row("echo", "Echo: responde repitiendo el mensaje")
        t.add_row("langgraph", "LangGraph: agente con LLM y herramientas")
        console.print(t)
        current = state.get("bot_mode") or "langgraph"
        default_bot_mode = current if current in ("echo", "langgraph") else "langgraph"
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
        _print_section(console, "Proveedor", "Configura el proveedor y modelo LLM.", "cyan")
        nav = _ask_provider(console, state)
        if nav:
            return True, "", nav
        return True, "", None

    if section_id == "deps":
        _print_section(console, "Dependencias", "Verificando paquetes requeridos...", "cyan")
        if not _check_dependencies(console):
            return False, "Corrige las dependencias y vuelve a esta sección.", None
        if state.get("bot_mode") == "langgraph" and not _check_langgraph_dependency(console):
            return False, "Instala LangGraph para modo langgraph.", None
        return True, "", None

    if section_id == "token":
        _print_section(console, "Token", "Se guarda en .env (excluido de git).", "cyan")
        env_dotenv = _load_dotenv_value(repo_root, "TELEGRAM_BOT_TOKEN")
        if os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
            state["token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            console.print(f"[dim]Token tomado de TELEGRAM_BOT_TOKEN: {_censor_token(state['token'])}[/]")
        elif env_dotenv:
            state["token"] = env_dotenv
            console.print(f"[dim]Token cargado desde .env: {_censor_token(env_dotenv)}[/]")
        else:
            val, nav = _prompt_with_nav(console, "TELEGRAM_BOT_TOKEN", password=True)
            if nav:
                return True, "", nav
            state["token"] = (val or "").strip()
        if not state.get("token", "").strip():
            return False, "El token es obligatorio.", None
        ok, err = _validate_token_format(state["token"])
        if not ok:
            return False, err, None
        _print_ok(console, "Formato correcto.")
        do_check = Confirm.ask("¿Validar token con Telegram ahora?", default=True)
        if do_check:
            with console.status("Comprobando con Telegram...", spinner="dots"):
                ok_api, err_api = _validate_token_with_api(state["token"])
            if not ok_api:
                return False, f"Telegram rechazó el token: {err_api}", None
            _print_ok(console, "Token validado.")
        # Persist token to .env for PM2 and future runs
        _write_env_token(state["token"], repo_root)
        return True, "", None

    if section_id == "db_path":
        _print_section(console, "DB", "Configura la ruta del archivo DuckDB.", "cyan")
        default_db = _normalize_db_path(
            os.environ.get("DUCKCLAW_DB_PATH")
            or state.get("db_path")
            or "db/telegram.duckdb"
        )
        val, nav = _prompt_with_nav(console, "DUCKCLAW_DB_PATH", default=default_db)
        if nav:
            return True, "", nav
        state["db_path"] = _normalize_db_path((val or "").strip() or "db/telegram.duckdb")
        return True, "", None

    if section_id == "validate_provider":
        _print_section(console, "Validar proveedor", "Comprobando requisitos del proveedor seleccionado.", "cyan")
        prov = (state.get("llm_provider") or "none_llm").strip().lower()
        ok_prov, err_prov = _validate_provider_config(
            console, prov,
            state.get("llm_model") or "",
            state.get("llm_base_url") or "",
        )
        if not ok_prov:
            return False, err_prov, None
        _print_ok(console, "Proveedor listo.")
        return True, "", None

    if section_id == "summary":
        _print_section(console, "Resumen", "Revisa la configuración antes de continuar.", "yellow")
        t = Table(title="Configuración actual", border_style="yellow")
        t.add_column("Clave", style="yellow")
        t.add_column("Valor", style="white")
        t.add_row("Canal", state.get("channel", ""))
        t.add_row("Modo del bot", state.get("bot_mode", ""))
        if _uses_provider_section(state.get("bot_mode", "")):
            t.add_row("Proveedor LLM", state.get("llm_provider") or "none_llm")
            if state.get("llm_model"):
                t.add_row("Modelo", state.get("llm_model"))
        t.add_row("Token (censurado)", _censor_token(state.get("token", "")))
        t.add_row("DB path", state.get("db_path", ""))
        t.add_row(
            "Persistencia",
            "Ya configurada" if state.get("service_persistence") == "already_configured" else "Configurar con PM2",
        )
        t.add_row("Modo setup", state.get("mode", ""))
        console.print(t)
        return True, "", None

    if section_id == "pm2":
        return _run_section_pm2(console, state, repo_root)

    if section_id == "save_launch":
        _print_section(console, "Finalizar", "Guarda configuración y opcionalmente arranca el bot.", "green")
        if Confirm.ask("¿Guardar esta configuración para la próxima vez?", default=True):
            save_config(
                mode=state.get("mode", "quick"),
                channel=state.get("channel", "telegram"),
                bot_mode=state.get("bot_mode", "bicameral"),
                db_path=_normalize_db_path(state.get("db_path", "db/telegram.duckdb")),
                llm_provider=state.get("llm_provider", ""),
                llm_model=state.get("llm_model", ""),
                llm_base_url=state.get("llm_base_url", ""),
                service_persistence=state.get("service_persistence", "setup_here"),
            )
        if _pm2_available() and Confirm.ask(
            "¿Quieres editar la configuración del servicio de persistencia (PM2) antes de arrancar?",
            default=False,
        ):
            _run_section_pm2(console, state, repo_root)

        if not Confirm.ask("¿Arrancar el bot de Telegram ahora?", default=True):
            console.print("[dim]Configuración guardada. Ejecuta el script del bot cuando quieras.[/]")
            return True, "", None
        env = os.environ.copy()
        # Ensure the repo root is in PYTHONPATH so `import core` works
        existing_pythonpath = env.get("PYTHONPATH", "")
        repo_root_str = str(repo_root)
        env["PYTHONPATH"] = (
            f"{repo_root_str}{os.pathsep}{existing_pythonpath}"
            if existing_pythonpath
            else repo_root_str
        )
        env["TELEGRAM_BOT_TOKEN"] = state.get("token", "")
        env["DUCKCLAW_DB_PATH"] = _normalize_db_path(state.get("db_path", "db/telegram.duckdb"))
        env["DUCKCLAW_BOT_MODE"] = state.get("bot_mode", "langgraph")
        if _uses_provider_section(state.get("bot_mode", "")):
            env["DUCKCLAW_LLM_PROVIDER"] = state.get("llm_provider") or "none_llm"
            env["DUCKCLAW_LLM_MODEL"] = state.get("llm_model", "")
            env["DUCKCLAW_LLM_BASE_URL"] = state.get("llm_base_url", "")
        console.print(Panel("Arrancando bot en modo polling...", border_style="cyan"))
        try:
            ret = subprocess.call(
                [sys.executable, str(bot_script)],
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
    bot_script = repo_root / "core" / "integrations" / "telegram_bot.py"

    state: dict[str, Any] = {}
    idx = 0

    try:
        while True:
            section_id = SECTION_IDS[idx]
            if section_id == "provider" and not _uses_provider_section(state.get("bot_mode", "")):
                idx = _next_index(idx, state) or idx
                continue
            if section_id == "validate_provider" and not _uses_provider_section(state.get("bot_mode", "")):
                idx = _next_index(idx, state) or idx
                continue
            # Si ya hay servicio configurado, saltar directamente a save_launch
            save_launch_idx = SECTION_IDS.index("save_launch")
            if state.get("service_persistence") == "already_configured" and section_id != "welcome" and idx < save_launch_idx:
                idx = save_launch_idx
                continue

            ok, err, nav = _run_section(section_id, console, state, repo_root, bot_script)
            if not ok:
                console.print(Panel(err, title="❌ Error", border_style="red"))

            if section_id == "welcome":
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

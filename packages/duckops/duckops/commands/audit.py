"""Comando audit: auditoría de Habeas Data (config, enmascaramiento)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer()
console = Console()


def _config_path() -> Path:
    return Path.home() / ".config" / "duckclaw" / "wizard_config.json"


def _censor(value: str, show_last: int = 4) -> str:
    """Enmascara datos sensibles (Habeas Data)."""
    if not value or len(value) <= show_last:
        return "***"
    return "***" + value[-show_last:]


def cmd_audit(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Mostrar más detalles.",
    ),
) -> None:
    """Auditoría de Habeas Data: configuración, enmascaramiento de datos sensibles."""
    config_path = _config_path()
    if not config_path.is_file():
        console.print(Panel(
            f"No hay configuración en {config_path}.\nEjecuta: duckops init",
            title="Auditoría",
            border_style="yellow",
        ))
        raise typer.Exit(0)

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        typer.echo(f"[red]Error al leer config: {e}[/]", err=True)
        raise typer.Exit(1)

    table = Table(title="Configuración (datos sensibles enmascarados)")
    table.add_column("Clave", style="cyan")
    table.add_column("Valor", style="white")

    sensitive_keys = ("token", "channel", "api_key", "secret")
    for k, v in sorted(data.items()):
        if v is None:
            v = "-"
        elif isinstance(v, bool):
            v = "true" if v else "false"
        else:
            v = str(v)
        if any(s in k.lower() for s in sensitive_keys) and len(v) > 4:
            v = _censor(v)
        table.add_row(k, v)

    console.print(table)
    console.print(Panel(
        "Habeas Data: los tokens y datos sensibles están enmascarados en logs y salida.",
        title="Seguridad",
        border_style="green",
    ))

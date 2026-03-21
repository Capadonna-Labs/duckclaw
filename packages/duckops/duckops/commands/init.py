"""Comando init: configuración inicial (env, db, tailscale)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer

app = typer.Typer()


def _repo_root() -> Path:
    """Raíz del monorepo (packages/duckops/duckops/commands -> ../../../../)."""
    return Path(__file__).resolve().parent.parent.parent.parent.parent


@app.callback(invoke_without_command=True)
def cmd_init(
    ctx: typer.Context,
    tenant_id: str = typer.Argument(
        default="default",
        help="ID del tenant (Multi-Vault / memoria industry); se expone al wizard como DUCKCLAW_TENANT_ID.",
    ),
    use_wizard: bool = typer.Option(
        True,
        "--wizard/--no-wizard",
        help="Ejecutar wizard interactivo (Rich).",
    ),
    industry: str | None = typer.Option(
        None,
        "--industry",
        help="Plantilla Forge (p.ej. business_standard). Define DUCKCLAW_INDUSTRY_TEMPLATE en el wizard.",
    ),
) -> None:
    """Inicializa un nuevo tenant con su base de datos y configuración."""
    if ctx.invoked_subcommand is not None:
        return
    repo = _repo_root()
    wizard_script = repo / "scripts" / "duckclaw_setup_wizard.py"

    if not wizard_script.is_file():
        typer.echo(f"[red]No se encontró el wizard: {wizard_script}[/]", err=True)
        raise typer.Exit(1)

    typer.secho(f"Forjando agente para {tenant_id}...", fg=typer.colors.CYAN)

    if use_wizard:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo) + (os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")
        env["DUCKCLAW_TENANT_ID"] = tenant_id.strip() or "default"
        if industry and industry.strip():
            env["DUCKCLAW_INDUSTRY_TEMPLATE"] = industry.strip()
        try:
            result = subprocess.run(
                [sys.executable, str(wizard_script)],
                cwd=str(repo),
                env=env,
            )
            if result.returncode != 0:
                raise typer.Exit(result.returncode)
        except KeyboardInterrupt:
            typer.echo("\nInterrumpido.")
            raise typer.Exit(130)
    else:
        typer.echo("Modo --no-wizard: ejecuta el wizard manualmente:")
        typer.echo(f"  python {wizard_script}")

    typer.secho("¡Agente listo!", fg=typer.colors.GREEN)

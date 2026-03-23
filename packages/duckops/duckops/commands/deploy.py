"""Comando deploy: despliegue en VPS/Mac (PM2, systemd, Windows)."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer()


def _repo_root() -> Path:
    """Raíz del monorepo."""
    return Path(__file__).resolve().parent.parent.parent.parent.parent


@app.callback(invoke_without_command=True)
def cmd_deploy(
    ctx: typer.Context,
    provider: str = typer.Option(
        "auto",
        "--provider",
        "-p",
        help="Proveedor: auto, pm2, systemd, windows, cron.",
    ),
    name: str = typer.Option(
        "DuckClaw-Brain",
        "--name",
        "-n",
        help="Nombre del servicio.",
    ),
) -> None:
    """Despliega el bot DuckClaw como servicio persistente."""
    if ctx.invoked_subcommand is not None:
        return
    repo = _repo_root()
    try:
        from duckclaw.ops.manager import deploy as deploy_fn
    except ImportError as e:
        typer.echo(f"[red]No se pudo importar duckclaw.ops: {e}[/]", err=True)
        typer.echo("Instala el monorepo: uv sync (o uv pip install -e . --no-build-isolation)")
        raise typer.Exit(1)

    typer.secho(f"Desplegando {name} con {provider}...", fg=typer.colors.CYAN)
    msg = deploy_fn(
        name=name,
        provider=provider,
        command="-m duckclaw.graphs.telegram_bot",
        cwd=str(repo),
    )
    typer.echo(msg)
    if "Error" in msg or "not implemented" in msg.lower():
        raise typer.Exit(1)
    typer.secho("Despliegue completado.", fg=typer.colors.GREEN)

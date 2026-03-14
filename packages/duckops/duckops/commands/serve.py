"""Comando serve: arranca el API Gateway o LangGraph server."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer()


def _repo_root() -> Path:
    """Raíz del monorepo."""
    return Path(__file__).resolve().parent.parent.parent.parent.parent


def cmd_serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host para escuchar."),
    port: int = typer.Option(8000, "--port", "-p", help="Puerto."),
    pm2: bool = typer.Option(False, "--pm2", help="Desplegar como servicio PM2."),
    gateway: bool = typer.Option(False, "--gateway", "-g", help="Usar duckclaw.api.gateway (n8n, Telegram)."),
    name: str = typer.Option(
        None,
        "--name",
        "-n",
        help="Nombre del servicio PM2 (default: DuckClaw-Gateway con --gateway, DuckClaw-API si no).",
    ),
    reload: bool = typer.Option(False, "--reload", help="Recargar al cambiar código (solo sin --pm2)."),
) -> None:
    """Arranca el API Gateway o el servidor LangGraph."""
    effective_name = name or ("DuckClaw-Gateway" if gateway else "DuckClaw-API")
    repo = _repo_root()
    try:
        from duckclaw.ops.manager import serve as serve_fn
    except ImportError as e:
        typer.echo(f"[red]No se pudo importar duckclaw.ops: {e}[/]", err=True)
        typer.echo("Instala el monorepo: uv sync")
        raise typer.Exit(1)

    code = serve_fn(
        host=host,
        port=port,
        reload=reload,
        pm2=pm2,
        name=effective_name,
        cwd=str(repo),
        gateway=gateway,
    )
    if code != 0:
        raise typer.Exit(code)

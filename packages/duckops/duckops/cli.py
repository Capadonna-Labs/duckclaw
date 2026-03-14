#!/usr/bin/env python3
"""DuckOps CLI — punto de entrada (Typer)."""

from __future__ import annotations

import typer

from duckops.commands import audit, deploy, init, serve

app = typer.Typer(
    name="duckops",
    help="DuckClaw CLI — Wizard, deploy y auditoría Habeas Data.",
    no_args_is_help=True,
)

app.command("init")(init.cmd_init)
app.command("deploy")(deploy.cmd_deploy)
app.command("serve")(serve.cmd_serve)
app.command("audit")(audit.cmd_audit)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

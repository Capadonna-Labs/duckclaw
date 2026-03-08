"""CLI for duckclaw.ops deploy."""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="duckops", description="Deploy and persist DuckClaw agents.")
    subparsers = parser.add_subparsers(dest="subcommand", help="Commands")

    deploy_parser = subparsers.add_parser("deploy", help="Deploy a command as a persistent service")
    deploy_parser.add_argument("--name", required=True, help="Service name")
    deploy_parser.add_argument(
        "--provider",
        choices=["pm2", "systemd", "cron", "windows", "auto"],
        default="auto",
        help="Deployment provider (default: auto)",
    )
    deploy_parser.add_argument("--command", required=True, help="Command to run (e.g. -m duckclaw.agents.telegram_bot)")
    deploy_parser.add_argument("--schedule", default=None, help="Optional cron expression (for cron provider)")
    deploy_parser.add_argument(
        "--windows-trigger",
        choices=["onlogon", "onstart"],
        default="onlogon",
        help="Windows: run at user logon or system startup (default: onlogon)",
    )
    deploy_parser.add_argument("--cwd", default=None, help="Working directory (default: current)")

    status_parser = subparsers.add_parser("status", help="Show persistence service summary")  # noqa: F841
    status_parser.add_argument(
        "--provider",
        choices=["pm2", "systemd", "windows", "auto"],
        default="auto",
        help="Provider to query (default: auto-detect)",
    )
    status_parser.add_argument(
        "--name",
        default=None,
        help="Filter by service name (default: show all DuckClaw services)",
    )

    serve_parser = subparsers.add_parser("serve", help="Start the LangGraph API server (LangSmith compatible)")
    serve_parser.add_argument("--host",   default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    serve_parser.add_argument("--port",   default=8123, type=int, help="Port (default: 8123)")
    serve_parser.add_argument("--reload", action="store_true", help="Auto-reload on file changes (dev mode)")
    serve_parser.add_argument("--pm2",    action="store_true", help="Deploy as PM2 service instead of running directly")
    serve_parser.add_argument("--name",   default="DuckClaw-API", help="PM2 service name (default: DuckClaw-API)")
    serve_parser.add_argument("--cwd",    default=None, help="Working directory (default: current)")
    serve_parser.add_argument("--gateway", action="store_true", help="Use API Gateway (duckclaw.api.gateway) instead of graph_server")

    hire_parser = subparsers.add_parser("hire", help="Deploy a Virtual Worker from template (Plug & Play)")
    hire_parser.add_argument("worker_id", nargs="?", default="", help="Template id (e.g. personal_finance, support)")
    hire_parser.add_argument("--name", "--instance", dest="instance_name", default=None, help="PM2 instance name (default: worker_id)")
    hire_parser.add_argument("--cwd", default=None, help="Working directory (default: current)")
    hire_parser.add_argument("--list", dest="list_workers", action="store_true", help="List available worker templates and exit")

    parsed = parser.parse_args(args)
    if not parsed.subcommand:
        parser.print_help()
        return 0

    if parsed.subcommand == "deploy":
        from duckclaw.ops.manager import deploy
        msg = deploy(
            name=parsed.name,
            provider=parsed.provider,
            command=parsed.command,
            schedule=parsed.schedule,
            cwd=parsed.cwd,
            windows_trigger=parsed.windows_trigger,
        )
        print(msg)
        low = msg.lower()
        failed = "error" in low or "unknown" in low or "not implemented" in low
        return 0 if not failed else 1

    if parsed.subcommand == "status":
        from duckclaw.ops.manager import status
        return status(provider=parsed.provider, name=parsed.name)

    if parsed.subcommand == "serve":
        from duckclaw.ops.manager import serve
        return serve(
            host=parsed.host,
            port=parsed.port,
            reload=parsed.reload,
            pm2=parsed.pm2,
            name=parsed.name,
            cwd=parsed.cwd,
            gateway=getattr(parsed, "gateway", False),
        )

    if parsed.subcommand == "hire":
        from duckclaw.ops.manager import hire
        if getattr(parsed, "list_workers", False):
            from duckclaw.workers.factory import list_workers
            for w in list_workers():
                print(w)
            return 0
        if not (parsed.worker_id or "").strip():
            hire_parser.print_help()
            return 1
        return hire(
            worker_id=(parsed.worker_id or "").strip(),
            instance_name=parsed.instance_name,
            cwd=parsed.cwd,
        )

    return 0


def _entrypoint() -> NoReturn:
    sys.exit(main())


if __name__ == "__main__":
    _entrypoint()

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
    return 0


def _entrypoint() -> NoReturn:
    sys.exit(main())


if __name__ == "__main__":
    _entrypoint()

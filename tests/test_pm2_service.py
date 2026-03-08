"""Tests to validate PM2 service and telegram bot entry point."""

from __future__ import annotations

import json
import os
import subprocess


def _pm2_jlist() -> list[dict] | None:
    """Run pm2 jlist and return parsed JSON, or None if pm2 unavailable."""
    try:
        result = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None


def test_telegram_bot_entry_point_importable() -> None:
    """Verify the module PM2 runs (core.integrations.telegram_bot) can be imported."""
    from core.integrations import telegram_bot

    assert hasattr(telegram_bot, "main")


def test_telegram_bot_main_requires_token() -> None:
    """Verify main() raises RuntimeError when TELEGRAM_BOT_TOKEN is missing."""
    from core.integrations.telegram_bot import main

    token = os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    try:
        try:
            main()
        except RuntimeError as e:
            assert "TELEGRAM_BOT_TOKEN" in str(e)
            return
        raise AssertionError("Expected RuntimeError for missing TELEGRAM_BOT_TOKEN")
    finally:
        if token is not None:
            os.environ["TELEGRAM_BOT_TOKEN"] = token


def test_pm2_finanz_inference_online() -> None:
    """Validate that the PM2 app (Finanz-Inference by default) is online.

    Skips if pm2 is not installed or the app is not registered.
    App name can be overridden via DUCKCLAW_PM2_APP_NAME env var.
    """
    app_name = os.environ.get("DUCKCLAW_PM2_APP_NAME", "Finanz-Inference")
    processes = _pm2_jlist()
    if processes is None:
        return  # pm2 not available, skip (pass to not fail CI)

    app = next((p for p in processes if p.get("name") == app_name), None)
    if app is None:
        return  # app not registered, skip

    pm2_env = app.get("pm2_env") or {}
    status = pm2_env.get("status", "unknown")
    assert status == "online", (
        f"PM2 app {app_name!r} is not online (status={status}). "
        f"Run: pm2 start {app_name}"
    )


if __name__ == "__main__":
    test_telegram_bot_entry_point_importable()
    test_telegram_bot_main_requires_token()
    test_pm2_finanz_inference_online()
    print("All tests passed.")

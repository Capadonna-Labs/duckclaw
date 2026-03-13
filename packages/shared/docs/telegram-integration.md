# Telegram Integration Guide (Third-Party Access)

This guide explains how to expose DuckClaw to a third party through Telegram using local polling and the built-in `TelegramBotBase`.

## Architecture

`TelegramBotBase` handles:
- table bootstrap (`telegram_messages`)
- automatic persistence of each incoming update
- optional app creation via `python-telegram-bot`

Flow:
1. Telegram sends an update to your bot.
2. `TelegramBotBase` persists the update into DuckClaw.
3. Your bot logic runs in `handle_message(update)`.

## 1) Create the Telegram bot token

1. Open Telegram and chat with **BotFather**.
2. Run `/newbot`.
3. Save the generated token.

Required environment variables:
- `TELEGRAM_BOT_TOKEN`
- `DUCKCLAW_DB_PATH` (optional, defaults to `telegram.duckdb`)

## 2) Install dependencies

From repo root:

```bash
pip install -e ".[telegram]" --no-build-isolation
```

If you prefer uv:

```bash
uv pip install -e ".[telegram]"
```

## 3) Run the bot locally (polling)

**Option A – Installer (wizard):** from repo root:

```bash
./scripts/install_duckclaw.sh
```

**Option B – Manual:** set env and run the sample:

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export DUCKCLAW_DB_PATH="telegram.duckdb"
python examples/telegram_bot.py
```

## 4) Validate persisted messages

```python
import duckclaw
db = duckclaw.DuckClaw("telegram.duckdb")
print(db.query("SELECT chat_id, username, text, received_at FROM telegram_messages ORDER BY received_at DESC LIMIT 20"))
```

## Troubleshooting

### Invalid token / Unauthorized
- Confirm token in `TELEGRAM_BOT_TOKEN`.
- Regenerate token in BotFather if needed.

### Missing optional dependency
- Error: `Telegram integration requires optional dependency python-telegram-bot`
- Fix:
  ```bash
  pip install -e ".[telegram]" --no-build-isolation
  ```

### `telegram_messages` table not created
- Ensure bot receives at least one message.
- Confirm you are opening the same DB file from `DUCKCLAW_DB_PATH`.

### Editable install errors (`No module named pip`)
- Use:
  ```bash
  pip install -e ".[telegram]" --no-build-isolation
  ```
  and install build deps in your venv if needed.

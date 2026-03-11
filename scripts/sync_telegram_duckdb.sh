#!/bin/bash
# Sincroniza telegram.duckdb desde el VPS (Capadonna) al Mac.
# Ejecutar antes de arrancar DuckClaw-Gateway o periódicamente si el VPS actualiza la BD.
#
# Uso: ./scripts/sync_telegram_duckdb.sh

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VPS_HOST="${DUCKCLAW_VPS_HOST:-capadonna@66.94.106.1}"
REMOTE_PATH="/home/capadonna/duckclaw/telegram.duckdb"
LOCAL_PATH="$REPO_ROOT/db/telegram.duckdb"

mkdir -p "$(dirname "$LOCAL_PATH")"
rsync -avz --progress "$VPS_HOST:$REMOTE_PATH" "$LOCAL_PATH"
echo "OK: $LOCAL_PATH sincronizado desde VPS"

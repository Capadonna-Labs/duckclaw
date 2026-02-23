#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "${ROOT_DIR}"

if command -v python3 >/dev/null 2>&1; then
  python3 scripts/duckclaw_setup_wizard.py
elif command -v python >/dev/null 2>&1; then
  python scripts/duckclaw_setup_wizard.py
else
  echo "Error: Python interpreter not found (python3/python)."
  exit 1
fi

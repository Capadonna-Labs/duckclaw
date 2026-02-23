#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "${ROOT_DIR}"

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "Error: Python interpreter not found (python3/python)."
  exit 1
fi

"${PYTHON}" scripts/duckclaw_setup_wizard.py

# Inicializar base de datos de finanzas e inventario (Capa de Negocio IoTCoreLabs)
if "${PYTHON}" -c "import duckclaw" 2>/dev/null; then
  "${PYTHON}" scripts/init_store_db.py
else
  echo "Nota: duckclaw no instalado aún; omitiendo init_store_db. Ejecuta después: ${PYTHON} scripts/init_store_db.py"
fi

# Si el bot está en PM2 y el proveedor es MLX, asegurar que DuckClaw-Inference (servidor MLX) esté en marcha
WIZARD_CFG="${HOME}/.config/duckclaw/wizard_config.json"
START_MLX=""
[ -f "${ROOT_DIR}/duckclaw/mlx/start_mlx.sh" ] && START_MLX="${ROOT_DIR}/duckclaw/mlx/start_mlx.sh"
[ -z "${START_MLX}" ] && [ -f "${ROOT_DIR}/mlx/start_mlx.sh" ] && START_MLX="${ROOT_DIR}/mlx/start_mlx.sh"
if command -v pm2 >/dev/null 2>&1 && pm2 describe DuckClaw-Brain >/dev/null 2>&1; then
  if [ -f "${WIZARD_CFG}" ] && grep -qE '"llm_provider"[[:space:]]*:[[:space:]]*"mlx"' "${WIZARD_CFG}" 2>/dev/null; then
    if [ -n "${START_MLX}" ] && ! pm2 describe DuckClaw-Inference >/dev/null 2>&1; then
      echo ""
      echo "Arrancando servidor de inferencia MLX (DuckClaw-Inference)..."
      if pm2 start bash --name DuckClaw-Inference --cwd "${ROOT_DIR}" -- "${START_MLX}"; then
        echo "DuckClaw-Inference en marcha. El bot podrá conectar al LLM local."
      else
        echo "Aviso: no se pudo arrancar DuckClaw-Inference. Ejecuta: pm2 start bash --name DuckClaw-Inference --cwd ${ROOT_DIR} -- ${START_MLX}"
      fi
    fi
  fi
fi

# Arrancar el bot solo si no está ya en marcha con PM2 (evita conflicto y lock de DuckDB)
if command -v pm2 >/dev/null 2>&1 && pm2 describe DuckClaw-Brain >/dev/null 2>&1; then
  echo ""
  echo "DuckClaw-Brain ya está en marcha con PM2. Mostrando logs (Ctrl+C para salir)..."
  exec pm2 logs DuckClaw-Brain
else
  echo ""
  echo "Arrancando bot DuckClaw agents..."
  exec "${PYTHON}" -m duckclaw.agents.telegram_bot
fi

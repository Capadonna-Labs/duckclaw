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

export PYTHONPATH="${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

"${PYTHON}" scripts/duckclaw_setup_wizard.py

# Inicializar base de datos de finanzas e inventario (Capa de Negocio IoTCoreLabs)
if "${PYTHON}" -c "import core" 2>/dev/null; then
  "${PYTHON}" scripts/init_store_db.py
else
  echo "Nota: paquete 'core' no disponible aún; omitiendo init_store_db. Ejecuta después: ${PYTHON} scripts/init_store_db.py"
fi

# Determinar nombre del servicio PM2 activo (Finanz-Inference o DuckClaw-Brain)
PM2_SERVICE=""
for svc in Finanz-Inference DuckClaw-Brain; do
  if command -v pm2 >/dev/null 2>&1 && pm2 describe "${svc}" >/dev/null 2>&1; then
    PM2_SERVICE="${svc}"
    break
  fi
done

# Si el bot está en PM2 y el proveedor es MLX, asegurar que DuckClaw-Inference (servidor MLX) esté en marcha
WIZARD_CFG="${HOME}/.config/duckclaw/wizard_config.json"
START_MLX=""
[ -f "${ROOT_DIR}/core/mlx/start_mlx.sh" ]     && START_MLX="${ROOT_DIR}/core/mlx/start_mlx.sh"
[ -z "${START_MLX}" ] && [ -f "${ROOT_DIR}/mlx/start_mlx.sh" ] && START_MLX="${ROOT_DIR}/mlx/start_mlx.sh"

if [ -n "${PM2_SERVICE}" ]; then
  if [ -f "${WIZARD_CFG}" ] && grep -qE '"llm_provider"[[:space:]]*:[[:space:]]*"mlx"' "${WIZARD_CFG}" 2>/dev/null; then
    if [ -n "${START_MLX}" ] && ! pm2 describe DuckClaw-Inference >/dev/null 2>&1; then
      echo ""
      echo "Arrancando servidor de inferencia MLX (DuckClaw-Inference)..."
      if pm2 start bash --name DuckClaw-Inference --cwd "${ROOT_DIR}" -- "${START_MLX}"; then
        echo "DuckClaw-Inference en marcha. El bot podrá conectar al LLM local."
      else
        echo "Aviso: no se pudo arrancar DuckClaw-Inference."
      fi
    fi
  fi
fi

# Arrancar el bot solo si no está ya en marcha con PM2 (evita conflicto y lock de DuckDB)
if [ -n "${PM2_SERVICE}" ]; then
  echo ""
  echo "${PM2_SERVICE} ya está en marcha con PM2. Mostrando logs (Ctrl+C para salir)..."
  exec pm2 logs "${PM2_SERVICE}"
else
  echo ""
  echo "Arrancando bot DuckClaw..."
  exec "${PYTHON}" -m duckclaw.agents.telegram_bot
fi

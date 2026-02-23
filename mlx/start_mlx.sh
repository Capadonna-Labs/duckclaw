#!/bin/bash
set -e
# Cargar .env del repo para MLX_MODEL_PATH y MLX_PYTHON (PM2 no carga .env al arrancar)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "${ROOT_DIR}/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "${ROOT_DIR}/.env"
  set +a
fi
# Rutas: desde .env o valores por defecto
PYTHON_PATH="${MLX_PYTHON:-/Users/juanjosearevalocamargo/Desktop/mlx_env/bin/python}"
MODEL_PATH="${MLX_MODEL_PATH:-/Users/juanjosearevalocamargo/Desktop/models/Slayer-8B-V1}"

if [ ! -x "$PYTHON_PATH" ]; then
  echo "Error: Python no encontrado o no ejecutable: $PYTHON_PATH. Exporta MLX_PYTHON si usas otro venv."
  exit 1
fi
if [ ! -d "$MODEL_PATH" ] && [ ! -f "$MODEL_PATH" ]; then
  echo "Error: Modelo no encontrado en: $MODEL_PATH. Exporta MLX_MODEL_PATH si usas otra ruta."
  exit 1
fi

MLX_PORT="${MLX_PORT:-8080}"
if command -v lsof >/dev/null 2>&1 && lsof -i :"${MLX_PORT}" -t >/dev/null 2>&1; then
  echo "Puerto ${MLX_PORT} ya está en uso. Ejecuta: pm2 stop DuckClaw-Inference; lsof -ti :${MLX_PORT} | xargs kill -9; sleep 2; pm2 start DuckClaw-Inference"
  echo "Quedando en espera para evitar reinicios en bucle (Ctrl+C o pm2 stop DuckClaw-Inference)."
  while true; do sleep 3600; done
fi

echo "🚀 Cargando modelo desde: $MODEL_PATH"
exec "$PYTHON_PATH" -m mlx_lm.server \
  --model "$MODEL_PATH" \
  --port "${MLX_PORT}" \
  --host 0.0.0.0

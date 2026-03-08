#!/bin/bash
# Hot-Swap: fusiona adapters LoRA en el modelo base y recarga DuckClaw-Inference.
# Spec: specs/Migracion_de_Pipeline_de_Entrenamiento_(GRPO_a_SFT_con_MLX).md
#
# Uso: ./scripts/mlx_hotswap.sh
# Requiere: mlx-lm[train], adapters en train/adapters/, MLX_MODEL_PATH en .env

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -f ".env" ]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

ADAPTERS_PATH="${SFT_ADAPTERS_PATH:-train/adapters}"
MODEL_PATH="${MLX_MODEL_PATH:-mlx-community/Llama-3.2-3B-Instruct-4bit}"
FUSED_PATH="${SFT_FUSED_PATH:-train/model_finetuned}"
PYTHON="${MLX_PYTHON:-python3}"

if [ ! -d "$ADAPTERS_PATH" ] || [ ! -f "$ADAPTERS_PATH/adapters.safetensors" ]; then
  echo "Error: adapters no encontrados en $ADAPTERS_PATH"
  echo "Ejecuta primero: python mlx/train_sft.py"
  exit 1
fi

echo "Fusionando adapters ($ADAPTERS_PATH) en modelo ($MODEL_PATH)..."
"$PYTHON" -m mlx_lm.fuse \
  --model "$MODEL_PATH" \
  --adapter-path "$ADAPTERS_PATH" \
  --save-path "$FUSED_PATH"

echo "Modelo fusionado en: $FUSED_PATH"
echo "Para usar: export MLX_MODEL_PATH=$ROOT/$FUSED_PATH"

# Model-Guard: evaluar antes del hot-swap (spec: Pipeline_de_Evaluacion_y_Validacion_de_Modelos)
echo "Evaluando modelo (Model-Guard)..."
if ! "$PYTHON" scripts/eval_model.py --model "$FUSED_PATH" --no-db; then
  echo "Modelo degradado. Abortando despliegue."
  exit 1
fi

echo "Modelo validado. Recargando DuckClaw-Inference..."
pm2 reload DuckClaw-Inference 2>/dev/null || echo "PM2 no disponible o DuckClaw-Inference no está en marcha. Reinicia manualmente."

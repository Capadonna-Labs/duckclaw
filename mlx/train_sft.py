#!/usr/bin/env python3
"""
MLX SFT Trainer — entrena con LoRA sobre dataset_sft.jsonl.

Spec: specs/Migracion_de_Pipeline_de_Entrenamiento_(GRPO_a_SFT_con_MLX).md

Requisitos: pip install "mlx-lm[train]"
Variables de entorno: SFT_DATASET_PATH, MLX_MODEL_PATH, SFT_ADAPTERS_PATH, MLX_PYTHON
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN_DIR = ROOT / "train"
DEFAULT_DATASET = TRAIN_DIR / "dataset_sft.jsonl"
DEFAULT_ADAPTERS = TRAIN_DIR / "adapters"
DEFAULT_MODEL = os.environ.get("MLX_MODEL_PATH", "mlx-community/Llama-3.2-3B-Instruct-4bit")


def main() -> int:
    dataset_path = Path(os.environ.get("SFT_DATASET_PATH", str(DEFAULT_DATASET)))
    adapters_path = Path(os.environ.get("SFT_ADAPTERS_PATH", str(DEFAULT_ADAPTERS)))
    model_path = os.environ.get("MLX_MODEL_PATH", DEFAULT_MODEL)
    python_path = os.environ.get("MLX_PYTHON", sys.executable)

    if not dataset_path.exists():
        print(f"Error: dataset no encontrado: {dataset_path}", file=sys.stderr)
        print("Ejecuta primero: python -c \"from duckclaw.forge.sft import collect_traces_to_sft; collect_traces_to_sft()\"", file=sys.stderr)
        return 1

    # mlx_lm.lora espera --data como directorio con train.jsonl
    data_dir = TRAIN_DIR / "sft_data_dir"
    data_dir.mkdir(parents=True, exist_ok=True)
    train_jsonl = data_dir / "train.jsonl"
    shutil.copy(dataset_path, train_jsonl)
    # test.jsonl mínimo (requerido por mlx_lm)
    test_jsonl = data_dir / "test.jsonl"
    if not test_jsonl.exists():
        with open(test_jsonl, "w", encoding="utf-8") as f:
            f.write('{"text": "<s>[INST] test [/INST] ok </s>"}\n')

    # Calcular iters: 1 epoch, batch_size 1
    num_lines = sum(1 for _ in open(dataset_path, encoding="utf-8") if _.strip())
    iters = max(10, num_lines)

    adapters_path.mkdir(parents=True, exist_ok=True)
    cmd = [
        python_path, "-m", "mlx_lm.lora",
        "--model", model_path,
        "--train",
        "--data", str(data_dir),
        "--iters", str(iters),
        "--batch-size", "1",
        "--learning-rate", "2e-5",
        "--lora-layers", "32",  # Llama-3.2-3B tiene 28 layers; 32 cubre todos
        "--adapter-path", str(adapters_path),
    ]
    print("Ejecutando:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Model-Guard: evalúa modelo finetuned antes del hot-swap.

Spec: specs/Pipeline_de_Evaluacion_y_Validacion_de_Modelos_(Model-Guard).md

Uso:
  python scripts/eval_model.py --model train/model_finetuned
  python scripts/eval_model.py --model train/model_finetuned --golden train/golden_dataset.jsonl --db-path olist.duckdb --threshold 0.95

Exit 0 si Promote (modelo apto), 1 si Abort (degradación detectada).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Carga .env si existe."""
    root = Path(__file__).resolve().parents[1]
    env_file = root / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key:
                        os.environ.setdefault(key, value)
        except Exception:
            pass


def main() -> int:
    _load_dotenv()

    parser = argparse.ArgumentParser(description="Model-Guard: evaluar modelo antes del hot-swap")
    parser.add_argument("--model", required=True, help="Ruta al modelo fusionado (MLX)")
    parser.add_argument("--golden", default="train/golden_dataset.jsonl", help="Ruta a golden_dataset.jsonl")
    parser.add_argument("--db-path", default="", help="Ruta a DuckDB con datos Olist (para LogicScore)")
    parser.add_argument("--data-dir", default="data", help="Directorio con CSV Olist para cargar en DB")
    parser.add_argument("--threshold", type=float, default=0.95, help="Umbral de accuracy para Promote")
    parser.add_argument("--max-tokens", type=int, default=512, help="Máximo tokens por generación")
    parser.add_argument("--no-db", action="store_true", help="No usar DuckDB (solo Accuracy, sin LogicScore)")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    model_path = (root / args.model).resolve() if not Path(args.model).is_absolute() else Path(args.model)
    golden_path = root / args.golden if not Path(args.golden).is_absolute() else Path(args.golden)

    if not model_path.exists():
        print(f"Error: modelo no encontrado: {model_path}", file=sys.stderr)
        return 1

    db = None
    data_dir = None
    if not args.no_db and args.db_path:
        db_path = root / args.db_path if not Path(args.db_path).is_absolute() else Path(args.db_path)
        data_dir = str(root / args.data_dir) if (root / args.data_dir).exists() else None
        try:
            import duckclaw

            db = duckclaw.DuckClaw(str(db_path))
        except Exception as e:
            print(f"Advertencia: no se pudo cargar DuckDB ({e}). Solo se evaluará Accuracy.", file=sys.stderr)
            db = None

    from duckclaw.forge.eval import evaluate_model

    promote, report = evaluate_model(
        str(model_path),
        golden_path=str(golden_path),
        db=db,
        data_dir=data_dir,
        threshold=args.threshold,
        max_tokens=args.max_tokens,
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nDecision: {report['decision']} (accuracy={report['accuracy']:.2%}, threshold={args.threshold})")
    if promote:
        print("Modelo validado. Realizando Hot-Swap...")
        return 0
    print("Modelo degradado. Abortando despliegue.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

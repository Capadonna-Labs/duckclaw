#!/usr/bin/env python3
"""Prueba mínima de DuckClaw en VPS (manifest, workers; opcional inferencia elástica)."""
import sys
import importlib.util
from pathlib import Path
# Repo root
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from duckclaw.workers.manifest import load_manifest
from duckclaw.workers.factory import list_workers

def main():
    workers = list_workers()
    print("Workers:", workers)
    spec = None
    try:
        spec = load_manifest("research_worker")
        print("research_worker inference_config:", getattr(spec, "inference_config", None))
    except TypeError as e:
        print("research_worker (manifest legacy, sin inference_config):", e)
        spec = None
    # Inferencia elástica (si existe hardware_detector en el repo)
    hd_path = root / "duckclaw" / "integrations" / "hardware_detector.py"
    if hd_path.exists() and spec is not None and getattr(spec, "inference_config", None):
        _spec = importlib.util.spec_from_file_location("hardware_detector", hd_path)
        hd = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(hd)
        device = hd.detect_hardware()
        print("Hardware detectado:", device)
        cfg = hd.get_inference_config(spec.inference_config)
        print("InferenceConfig:", cfg.provider, cfg.device, cfg.model_id)
    else:
        print("Hardware detector: no presente en este clone (inferencia elástica)")
    print("DuckClaw OK")
    return 0

if __name__ == "__main__":
    sys.exit(main())

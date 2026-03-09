"""
Inferencia Elástica (Hardware-Aware): detección de capacidades al arranque.

Spec: specs/Inferencia_Elastica_(Hardware-Aware).md

- Check 1 (Apple Silicon): MLX Metal.
- Check 2 (NVIDIA): CUDA vía PyTorch.
- Check 3: Fallback -> mode "cloud".

Salida: InferenceConfig (provider, device, model_path) para el InferenceRouter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class InferenceConfig:
    """Configuración de inferencia resuelta por HardwareDetector + manifest."""

    provider: str  # "mlx" | "ollama" (cuda) | "groq" | "openai" | ...
    device: Optional[str]  # "metal" | "cuda" | None (cloud)
    model_path: Optional[str] = None  # ruta local o ID de modelo
    model_id: Optional[str] = None  # modelo cloud (ej. llama-3.3-70b)


def detect_hardware() -> Optional[str]:
    """
    Detecta el dispositivo de inferencia disponible.
    Orden: Apple Silicon (Metal) -> NVIDIA (CUDA) -> None (sin GPU local).

    Returns:
        "metal" si MLX/Metal está disponible.
        "cuda" si PyTorch CUDA está disponible.
        None si no hay GPU local (fallback a cloud).
    """
    # Check 1: Apple Silicon (MLX Metal)
    try:
        import mlx.core as mx
        if getattr(mx, "metal", None) is not None and mx.metal.is_available():
            logger.info("HardwareDetector: Apple Silicon (Metal) detectado.")
            return "metal"
    except ImportError:
        pass
    except Exception as e:
        logger.debug("MLX no disponible: %s", e)

    # Check 2: NVIDIA CUDA
    try:
        import torch
        if getattr(torch, "cuda", None) is not None and torch.cuda.is_available():
            logger.info("HardwareDetector: NVIDIA CUDA detectado.")
            return "cuda"
    except ImportError:
        pass
    except Exception as e:
        logger.debug("PyTorch CUDA no disponible: %s", e)

    logger.info("HardwareDetector: no se detectó GPU local. Modo cloud.")
    return None


def build_inference_config(
    device: Optional[str],
    inference_manifest: Optional[dict] = None,
    *,
    fallback_to_cloud: bool = True,
    cloud_provider: str = "groq",
    cloud_model: str = "llama-3.3-70b-versatile",
    model_path: Optional[str] = None,
) -> InferenceConfig:
    """
    Construye InferenceConfig a partir del dispositivo detectado y del manifest.

    Si device es None y fallback_to_cloud es True, devuelve config para API (cloud).
    Si device es "metal", provider = "mlx".
    Si device es "cuda", provider = "ollama" (llama.cpp / servidor local con GPU).
    """
    inference_manifest = inference_manifest or {}
    fallback = inference_manifest.get("fallback_to_cloud", fallback_to_cloud)
    cloud_prov = (inference_manifest.get("cloud_provider") or cloud_provider).strip().lower()
    cloud_mod = (inference_manifest.get("cloud_model") or cloud_model).strip()

    if device == "metal":
        return InferenceConfig(
            provider="mlx",
            device="metal",
            model_path=model_path or inference_manifest.get("model_path"),
            model_id=None,
        )
    if device == "cuda":
        return InferenceConfig(
            provider="ollama",  # llama.cpp con CUDA o Ollama local
            device="cuda",
            model_path=model_path or inference_manifest.get("model_path"),
            model_id=inference_manifest.get("cuda_model") or "llama3.2",
        )
    # Sin GPU local
    if fallback:
        logger.info("Inferencia elástica: usando cloud (%s, %s).", cloud_prov, cloud_mod)
        return InferenceConfig(
            provider=cloud_prov,
            device=None,
            model_path=None,
            model_id=cloud_mod,
        )
    raise RuntimeError(
        "No se detectó GPU local (Metal/CUDA) y fallback_to_cloud está desactivado. "
        "Activa inference.fallback_to_cloud en el manifest o configura MLX/CUDA."
    )


def resolve_llm_params_from_config(config: InferenceConfig) -> tuple[str, str, str]:
    """
    InferenceRouter: convierte InferenceConfig en (provider, model, base_url)
    para build_llm(). Así se enruta inferencia a MLX, CUDA/Ollama o API sin cambiar el core.
    """
    base_url = ""
    if config.provider == "mlx":
        import os
        base_url = (os.environ.get("DUCKCLAW_LLM_BASE_URL") or "http://127.0.0.1:8080/v1").strip()
        model = (config.model_path or config.model_id or "").strip() or ""
        return ("mlx", model, base_url)
    if config.provider == "ollama":
        base_url = (__import__("os").environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").strip()
        model = (config.model_id or config.model_path or "llama3.2").strip()
        return ("ollama", model, base_url)
    # Cloud
    model = (config.model_id or "").strip()
    return (config.provider, model, base_url)


def get_inference_config(
    inference_manifest: Optional[dict] = None,
) -> InferenceConfig:
    """
    Punto de entrada: detecta hardware una vez y devuelve InferenceConfig.
    Usar al iniciar el proceso (p. ej. en factory al crear el worker).
    """
    device = detect_hardware()
    return build_inference_config(device, inference_manifest)

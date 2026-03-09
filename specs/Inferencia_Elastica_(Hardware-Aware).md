# Inferencia Elástica (Hardware-Aware)

## 1. Objetivo Arquitectónico
Implementar un nodo de **Detección de Capacidades (Capability Detection)** que configure el motor de inferencia al arrancar el proceso. El sistema debe ser capaz de conmutar entre `MLX` (Apple Silicon), `CUDA` (NVIDIA/Linux) o `API-Only` (Cloud) de forma transparente para el agente.

## 2. Especificación de Skill: `HardwareDetector`

Este nodo se ejecuta una sola vez al iniciar el proceso (`factory.py`).

*   **Lógica de Detección:**
    1.  **Check 1 (Apple Silicon):** `import mlx.core as mx` -> `mx.metal.is_available()`.
    2.  **Check 2 (NVIDIA CUDA):** `import torch` -> `torch.cuda.is_available()`.
    3.  **Check 3 (Fallback):** Si ambos fallan, marcar `mode: "cloud"`.
*   **Salida:** `InferenceConfig` (provider, device, model_path).

## 3. Especificación de Skill: `InferenceRouter`

Este nodo gestiona la ejecución de la inferencia en tiempo real.

*   **Entrada:** `prompt`, `InferenceConfig`.
*   **Lógica:**
    ```python
    def route_inference(prompt, config):
        if config.device == "metal":
            return MLX_Inference(prompt)
        elif config.device == "cuda":
            return Torch_Inference(prompt) # llama.cpp con soporte CUDA
        else:
            return API_Inference(prompt) # Groq/OpenAI
    ```

## 4. Adaptación del Core (C++ y Python)

### A. C++ Core (`duckclaw.cpp`)
Debes usar **`llama.cpp`** como backend universal, ya que soporta los tres modos:
*   **Metal:** `-ngl 99` (Apple Silicon).
*   **CUDA:** `-ngl 99` (NVIDIA).
*   **CPU/API:** Si no hay GPU, el binario debe compilarse con soporte `LLAMA_CPU` y el agente debe configurarse para usar el `APIProvider`.

### B. Dockerfile Multi-Stage (Linux)
Para que esto funcione en tu VPS (Linux), el `Dockerfile` debe ser inteligente:

```dockerfile
# Etapa 1: Build
FROM ubuntu:22.04 AS builder
RUN apt-get update && apt-get install -y cmake build-essential
# Detectar si hay soporte CUDA en el build
ARG USE_CUDA=0
RUN if [ "$USE_CUDA" = "1" ]; then apt-get install -y nvidia-cuda-toolkit; fi
RUN make # Compila llama.cpp con los flags detectados

# Etapa 2: Runtime
FROM ubuntu:22.04
# Copiar binarios compilados
```

## 5. Protocolo de Configuración (Manifest)

El `manifest.yaml` ahora es dinámico:

```yaml
# duckclaw/workers/manifest.yaml
inference:
  fallback_to_cloud: true # Si la GPU falla, usar API
  cloud_provider: "groq"
  cloud_model: "llama-3.3-70b"
```

## 6. Integración en el `factory.py`

El `factory.py` ahora es el orquestador de hardware:

```python
def initialize_worker(worker_id):
    config = load_manifest(worker_id)
    
    # Detección automática
    device = detect_hardware() # metal, cuda, o None
    
    if device is None and config.get('fallback_to_cloud'):
        logger.info("No GPU detected. Switching to Cloud API.")
        provider = APIProvider(config['cloud_provider'])
    else:
        provider = LocalProvider(device=device)
        
    return Agent(provider=provider)
```

## 7. Ventajas de esta Arquitectura
1.  **Portabilidad Total:** El mismo código corre en tu Mac Mini (Metal), en un servidor con GPU NVIDIA (CUDA) y en un VPS barato (Cloud API).
2.  **Resiliencia:** Si tu GPU falla (ej. error de driver), el sistema detecta la caída y conmuta automáticamente a la API (Cloud) para que el bot no deje de responder.
3.  **Habeas Data:** El sistema siempre preferirá la inferencia local si detecta hardware capaz. Solo usará la API si es estrictamente necesario para mantener el servicio activo.
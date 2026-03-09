# Inferencia Elástica — build Linux con soporte opcional CUDA.
# Spec: specs/Inferencia_Elastica_(Hardware-Aware).md §4.B
#
# Build sin CUDA:  docker build -t duckclaw/inference:latest docker/inference/
# Build con CUDA:  docker build --build-arg USE_CUDA=1 -t duckclaw/inference:cuda docker/inference/

# Etapa 1: Builder (compila llama.cpp o binarios de inferencia)
FROM ubuntu:22.04 AS builder
ARG USE_CUDA=0
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Soporte CUDA opcional para VPS con GPU NVIDIA
RUN if [ "$USE_CUDA" = "1" ]; then \
    apt-get update && apt-get install -y --no-install-recommends nvidia-cuda-toolkit; \
    fi

# Cuando se integre llama.cpp: clonar y compilar con -DGGML_CUDA=ON si USE_CUDA=1
# RUN git clone https://github.com/ggerganov/llama.cpp /tmp/llama.cpp && cd /tmp/llama.cpp && \
#     cmake -B build -DGGML_CUDA=$([ "$USE_CUDA" = "1" ] && echo "ON" || echo "OFF") && cmake --build build
# Por ahora no hay binario; la inferencia en Docker usa API (cloud) o Ollama externo.
WORKDIR /build

# Etapa 2: Runtime (imagen mínima para ejecutar workers con fallback API)
FROM ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copiar binarios desde builder cuando existan (ej. llama.cpp)
# COPY --from=builder /tmp/llama.cpp/build/bin/llama-cli /usr/local/bin/ || true

WORKDIR /app
ENV PYTHONUNBUFFERED=1
# Inferencia elástica: sin GPU en contenedor -> fallback_to_cloud en manifest
ENV DUCKCLAW_LLM_PROVIDER=""
ENV DUCKCLAW_LLM_MODEL=""

# El proceso principal lo lanza el orquestador (PM2/docker-compose) con el repo DuckClaw
CMD ["python3", "-c", "print('Inference runtime: use fallback_to_cloud or mount Ollama/MLX server.')"]

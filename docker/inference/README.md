# Inferencia Elástica (Docker)

Spec: [Inferencia_Elastica_(Hardware-Aware).md](../../specs/Inferencia_Elastica_(Hardware-Aware).md) §4.B.

- **Sin CUDA:** `docker build -t duckclaw/inference:latest docker/inference/`
- **Con CUDA (NVIDIA):** `docker build --build-arg USE_CUDA=1 -t duckclaw/inference:cuda docker/inference/`

En runtime, sin GPU en el contenedor, el worker usa `inference.fallback_to_cloud` del manifest (Groq/OpenAI/etc.). Para inferencia local en Docker se puede montar un servidor Ollama/MLX o exponer el socket.

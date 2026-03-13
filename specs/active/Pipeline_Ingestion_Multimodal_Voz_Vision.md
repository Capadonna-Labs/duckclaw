# Pipeline de Ingestión Multimodal (Voz y Visión Local)

## 1. Objetivo

Procesar notas de voz (WhatsApp) y fotografías sin APIs externas. Normalizar a texto antes de inyectar en LangGraph. Habeas Data: borrado seguro de datos biométricos (voz).

## 2. Topología

```
WhatsApp/n8n → POST /media → Guardar /tmp → ARQ → {Audio→Whisper | Imagen→Vision}
→ <audio_transcription>texto</audio_transcription> | <image_description>texto</image_description>
→ LangGraph → Borrado seguro
```

## 3. AudioTranscriber (MLX Whisper)

- **Motor:** mlx-whisper (Apple Silicon)
- **Entrada:** /tmp/duckclaw_media/audio_{uuid}.ogg
- **Salida:** texto
- **Post:** `<audio_transcription>{texto}</audio_transcription>`
- **Habeas Data:** `os.remove(file_path)` en finally

## 4. VisionInterpreter (Edge Vision)

- **Motor:** mlx-vlm (Moondream2 / Llama-Vision)
- **Entrada:** /tmp/duckclaw_media/img_{uuid}.jpg
- **Salida:** descripción
- **Post:** `<image_description>{texto}</image_description>`

## 5. API Gateway

**POST /api/v1/agent/{worker_id}/media/{thread_id}**

- Body: multipart/form-data (archivo)
- MIME: audio/ogg, audio/mpeg, image/jpeg, image/png
- Guardar: /tmp/duckclaw_media/{uuid}.{ext}
- Encolar: ARQ process_multimodal_input
- Respuesta: `{"status": "processing", "task_id": "uuid"}`

## 6. Habeas Data

- **Voz:** Borrado físico en finally (os.remove)
- **tmpfs:** `./scripts/setup_media_tmpfs.sh` monta /tmp/duckclaw_media en RAM
- **Auditoría:** Solo texto en LangSmith, nunca binario

## 7. Uso

```bash
# Requiere Redis + ARQ
export REDIS_URL=redis://localhost:6379
uv run arq duckclaw.activity.worker.WorkerSettings

# Upload (n8n, curl)
curl -X POST -H "X-Tailscale-Auth-Key: $KEY" \
  -F "file=@nota.ogg" \
  https://gateway/api/v1/agent/powerseal/media/wa-123

# Poll resultado
curl "https://gateway/api/v1/activity/job/{task_id}"
```

## 8. Dependencias

- **multimodal:** `uv sync --extra multimodal` (mlx-whisper, Pillow)
- mlx-whisper requiere Apple Silicon o fallback a transcripción vacía

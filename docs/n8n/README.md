# Workflows n8n → DuckClaw Gateway

## Archivos

| Archivo | Uso |
|---------|-----|
| `workflow-duckclaw-finanz-telegram.json` | Bot Finanz → **Finanz-Gateway** puerto **8000** |
| `workflow-duckclaw-the-mind-telegram.json` | Bot The Mind → **TheMind-Gateway** puerto **8080** |

**Importar:** en n8n → menú ⋮ → **Import from File** → elige el JSON.

## Después de importar

1. **Credenciales Telegram** en **Telegram Trigger** y **Responder Telegram** (mismo bot que debe recibir/enviar mensajes).
2. **URL del gateway** en el nodo **HTTP Request** (campo URL):
   - Finanz: por defecto `http://127.0.0.1:8000/api/v1/agent/chat`
   - The Mind: por defecto `http://127.0.0.1:8080/api/v1/agent/chat`  

   Si n8n está en un servidor y DuckClaw en tu Mac, cambia `127.0.0.1` por la **IP Tailscale** del Mac (ej. `http://100.97.151.69:8000/api/v1/agent/chat`).

3. **Un solo Telegram Trigger por bot** (limitación de la API de Telegram). Si tienes dos flujos con el mismo token, solo uno recibirá updates.

4. **Activar** el workflow (toggle Active).

## Body enviado al API

Coincide con `ChatRequest` del gateway:

- `message` — texto del usuario  
- `chat_id` — ID del chat (string)  
- `user_id` — ID Telegram del remitente (**obligatorio para Telegram Guard** en grupos; en DM el gateway también acepta solo `chat_id` si `chat_type` es private)  
- `username`, `chat_type`, `tenant_id`

La respuesta del gateway incluye `response` (texto a reenviar al usuario).

## Si el import falla

Las versiones de n8n cambian `typeVersion` de nodos. Abre el workflow vacío, añade a mano **Telegram Trigger → HTTP Request → Telegram (sendMessage)** y copia del JSON solo el **jsonBody** del HTTP y las conexiones, o sube de versión n8n.

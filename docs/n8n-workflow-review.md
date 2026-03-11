# Revisión del workflow n8n DuckClaw

Flujo: **Telegram Trigger → DuckClaw API Gateway (Mac Mini) → Responder Telegram**

## Checklist de configuración

### 1. URL del API Gateway

El nodo "DuckClaw API Gateway" debe apuntar a la **Mac Mini** (donde corre DuckClaw-Gateway):

- **Si el Gateway está en la Mac Mini:** usa la IP Tailscale de la Mac Mini.
  ```bash
  # En la Mac Mini
  tailscale ip -4
  ```
  URL: `http://<IP_TAILSCALE_MAC_MINI>:8000/api/v1/agent/chat`

- **Si el Gateway está en el VPS:** usa `http://127.0.0.1:8000/api/v1/agent/chat` (n8n y Gateway en el mismo host).

El workflow usa `100.99.72.63` (IP Tailscale de la Mac Mini). Si la IP cambia, ejecuta `tailscale ip -4` en la Mac Mini y actualiza el nodo.

### 2. Autenticación

- Header `X-Tailscale-Auth-Key` debe coincidir con `DUCKCLAW_TAILSCALE_AUTH_KEY` en el `.env` de la Mac Mini.
- Valor actual en el workflow: `n8n_secret_key_12345`.

### 3. Credenciales de Telegram

- Sustituye `COLOQUE_SU_ID_AQUI` por el ID real de las credenciales de Telegram en n8n.
- El Trigger y el Responder deben usar la misma cuenta/bot.

### 4. Body del request

Formato esperado por el API:

```json
{
  "message": "{{ $json.message.text }}",
  "session_id": "{{ $json.message.chat.id }}",
  "stream": false
}
```

- `session_id` = `chat.id` para mantener historial por conversación.

### 5. Respuesta del API

- Éxito: `{"response": "...", "session_id": "..."}`
- Error 401: `{"detail": "X-Tailscale-Auth-Key inválida o faltante"}`
- Error 503: servicio no disponible

El Responder usa `$json.response` y, si falla, `$json.detail` o un mensaje por defecto.

## Resumen del flujo

```
Telegram (usuario) 
    → n8n Telegram Trigger (recibe mensaje)
    → HTTP POST a DuckClaw-Gateway (Mac Mini :8000)
    → API procesa con Finanz worker (get_ibkr_portfolio, run_sql, etc.)
    → n8n Responder Telegram (envía respuesta)
    → Telegram (usuario)
```

## Verificación

```bash
# Desde la Mac Mini (Gateway local)
curl -X POST http://localhost:8000/api/v1/agent/chat \
  -H "X-Tailscale-Auth-Key: n8n_secret_key_12345" \
  -H "Content-Type: application/json" \
  -d '{"message":"hola","session_id":"test","stream":false}'
```

Debe retornar `{"response":"...","session_id":"test"}`.

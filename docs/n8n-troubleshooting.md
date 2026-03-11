# n8n + Telegram: Resolución de problemas

## 1. Las peticiones no llegan (401)

**Causa:** `X-Tailscale-Auth-Key` no coincide con `DUCKCLAW_TAILSCALE_AUTH_KEY` en la Mac Mini.

**Solución:** En `.env` de la Mac Mini (donde corre el API Gateway):

```env
DUCKCLAW_TAILSCALE_AUTH_KEY=n8n_secret_key_12345
```

El valor debe ser **idéntico** al header `X-Tailscale-Auth-Key` del nodo "DuckClaw API Gateway" en n8n.

## 2. Respuestas sin formato en Telegram

**Causa:** El Gateway no tiene el código actualizado o la base de datos no tiene transacciones.

**Solución:**
1. Reinicia el Gateway en la Mac Mini: `pm2 restart DuckClaw-Gateway`
2. Si usas `finanz.duckdb` en otra ruta, añade en `.env`:
   ```env
   DUCKCLAW_DB_PATH=/ruta/a/finanz.duckdb
   ```

## 3. Trazas en LangSmith

Las trazas "ChatOpenAI" con output "ai: NINGUNA..." provienen del extractor RAG (graph_rag), no del agente principal. Es el comportamiento esperado cuando no hay tripletas que extraer.

Para el agente Finanz, revisa las trazas "LangGraph" en el proyecto Finanz.

## 4. Reiniciar servicios

**Mac Mini (Gateway):**
```bash
pm2 restart DuckClaw-Gateway
# o si usas ecosystem.hybrid:
pm2 restart ecosystem.hybrid.config.cjs
```

**VPS (n8n):**
```bash
ssh capadonna@66.94.106.1 "docker restart n8n-n8n-1"
```

## 5. Verificar integración

```bash
# Desde la Mac Mini
curl -X POST http://localhost:8000/api/v1/agent/chat \
  -H "X-Tailscale-Auth-Key: n8n_secret_key_12345" \
  -H "Content-Type: application/json" \
  -d '{"message":"hola","session_id":"test","stream":false}'
```

Debe retornar `{"response":"...","session_id":"test"}`.

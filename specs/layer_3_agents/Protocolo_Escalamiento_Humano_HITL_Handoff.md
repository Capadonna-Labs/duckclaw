# Protocolo de Escalamiento Humano (HITL Handoff)

## 1. Objetivo

Transferencia de control determinista entre el agente y un operador humano. El sistema pausa la inferencia, mantiene el contexto y enruta mensajes vía n8n hacia interfaz humana.

## 2. Máquina de Estados (Redis)

| Estado | Descripción |
|--------|-------------|
| IDLE | Agente disponible |
| BUSY | Agente procesando |
| HANDOFF_REQUESTED | Agente solicitó ayuda, esperando humano |
| MANUAL_MODE | Humano tiene control; agente ignora mensajes |

Clave: `session_state:{thread_id}` (hash: status, context_summary, requested_at)

## 3. HandoffTrigger (Skill)

- **Entrada:** reason, context_summary
- **Lógica:** Mutar Redis → HANDOFF_REQUESTED, webhook n8n, HandoffInterrupt
- **Salida:** "He notificado a un especialista. Te contactarán en breve."

## 4. Criterios de Escalamiento Autónomo

- **RAG Miss:** CatalogRetriever vacío en 2 turnos consecutivos
- **Sentimiento:** Frustración o urgencia crítica
- **Petición explícita:** "asesor", "humano", "llamar"

## 5. API Gateway

- **Interceptor:** Si MANUAL_MODE → `{"status": "ignored", "reason": "manual_mode_active"}`
- **POST /api/v1/thread/{thread_id}/takeover** → MANUAL_MODE
- **POST /api/v1/thread/{thread_id}/release** → IDLE (inyecta historial humano)
- **GET /api/v1/thread/{thread_id}/status** → estado actual

## 6. Habeas Data

- **author_type:** AI | HUMAN en api_conversation (auditoría)
- **DataMasker:** Aplicar a mensajes humanos antes de inyectar en memoria del agente

## 7. Integración n8n

1. **Trigger:** Mensaje entrante (WhatsApp, etc.)
2. **HTTP GET** `/api/v1/thread/{thread_id}/status`
3. **Switch:**
   - IDLE/BUSY → POST `/api/v1/agent/{worker_id}/chat` (IA responde)
   - MANUAL_MODE → Enrutar a grupo Soporte: `[Cliente {Teléfono}]: {Mensaje}`
   - HANDOFF_REQUESTED → Alerta: 🚨 Requiere atención: {context_summary}
4. **Webhook:** HITL_N8N_WEBHOOK_URL recibe payload al invocar handoff_trigger

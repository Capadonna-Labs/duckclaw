# Homeostasis: "¿Qué tarea hacer?" con n8n

El sistema puede preguntar al usuario "¿Qué tarea quieres que haga?" en dos momentos:

1. **Al completar una tarea** (chat síncrono o ARQ)
2. **Esporádicamente** según un timer systemd (cada 2 horas por defecto)

El canal de entrega es **n8n**: el API Gateway envía un webhook a n8n, y el usuario configura en n8n el workflow que envía el mensaje (Telegram, email, etc.).

## Variables de entorno

| Variable | Descripción |
|----------|-------------|
| `N8N_HOMEOSTASIS_ASK_TASK_WEBHOOK_URL` | URL del webhook de n8n que recibe el evento "ask_task" |
| `DUCKCLAW_HOMEOSTASIS_OBJECTIVES` | Objetivos sugeridos para priorizar (JSON array). Ejemplo: `["Aumentar ventas de categoría X","Disminuir tiempo de respuesta"]` |

Ejemplo de `DUCKCLAW_HOMEOSTASIS_OBJECTIVES`:
```bash
export DUCKCLAW_HOMEOSTASIS_OBJECTIVES='["Aumentar ventas de categoría X","Disminuir tiempo de respuesta","Mejorar disponibilidad de stock"]'
```

## Formato del payload

El API Gateway envía un POST a la URL configurada con:

```json
{
  "trigger": "task_complete",
  "message": "¿Qué tarea quieres que haga?",
  "worker_id": "powerseal",
  "session_id": "default",
  "suggested_objectives": [
    "Aumentar ventas de cierta categoría",
    "Disminuir tiempo de respuesta",
    "Mejorar disponibilidad de stock",
    "Optimizar presupuesto o tasa de ahorro"
  ]
}
```

- `trigger`: `"task_complete"` (cuando termina un chat) o `"timer"` (cuando dispara el timer systemd)
- `message`: texto fijo para el usuario
- `worker_id`: ID del worker que procesó la tarea (vacío si es timer)
- `session_id`: ID de sesión
- `suggested_objectives`: lista de objetivos para priorizar (configurable vía `DUCKCLAW_HOMEOSTASIS_OBJECTIVES`)

## Configurar workflow en n8n

1. Crear un workflow en n8n:
   - **Nodo Webhook** (POST): URL que se configurará como `N8N_HOMEOSTASIS_ASK_TASK_WEBHOOK_URL`
   - **Nodo siguiente**: enviar mensaje por Telegram (o el canal deseado) con el texto que incluya la pregunta y los objetivos sugeridos:
     - `{{ $json.body.message }}` — pregunta base
     - `{{ $json.body.suggested_objectives }}` — lista de objetivos para priorizar (formatear como bullets o botones)

2. Activar el workflow para que el webhook esté disponible.

3. Configurar `N8N_HOMEOSTASIS_ASK_TASK_WEBHOOK_URL` en el entorno del API Gateway (ej. en `.env` o en el unit file de systemd).

## systemd

### DuckClaw-Gateway.service

Servicio para el API Gateway (puerto 8000). **Ejecutar desde el directorio del proyecto en el VPS** (ej. `/home/capadonna/duckclaw`):

**Opción rápida** (script que instala todo):
```bash
bash scripts/install_systemd_gateway.sh
```

**Opción manual**:
```bash
sudo cp scripts/systemd/DuckClaw-Gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable DuckClaw-Gateway
sudo systemctl start DuckClaw-Gateway
```

### DuckClaw-Homeostasis-TaskAsk (timer + service)

Para la pregunta esporádica cada 2 horas (ejecutar desde el directorio del proyecto en el VPS):

```bash
sudo cp scripts/systemd/DuckClaw-Homeostasis-TaskAsk.service /etc/systemd/system/
sudo cp scripts/systemd/DuckClaw-Homeostasis-TaskAsk.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable DuckClaw-Homeostasis-TaskAsk.timer
sudo systemctl start DuckClaw-Homeostasis-TaskAsk.timer
```

**Ver estado del timer:**
```bash
systemctl list-timers DuckClaw-Homeostasis-TaskAsk.timer
```

**Cambiar intervalo:** editar `OnCalendar` en `DuckClaw-Homeostasis-TaskAsk.timer`:
- `*:00/2:00` = cada 2 horas
- `*:00/4:00` = cada 4 horas
- `Mon..Fri *:00/4:00` = cada 4 horas en días laborables

## Endpoint manual

Para disparar la pregunta manualmente:

```bash
curl -X POST -H "Content-Type: application/json" -d '{}' http://localhost:8000/api/v1/homeostasis/ask_task
```

Con worker_id, session_id y objetivos opcionales:

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"worker_id":"powerseal","session_id":"default"}' \
  http://localhost:8000/api/v1/homeostasis/ask_task
```

Con objetivos personalizados para priorizar:

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"suggested_objectives":["Aumentar ventas de categoría X","Disminuir tiempo de respuesta"]}' \
  http://localhost:8000/api/v1/homeostasis/ask_task
```

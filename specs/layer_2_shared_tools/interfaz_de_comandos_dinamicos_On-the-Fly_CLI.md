# Interfaz de Comandos Dinámicos (On-the-Fly CLI)

## 1. Objetivo Arquitectónico
Definir el contrato de la interfaz de comandos (CLI) para el bot de Telegram. Estos comandos actúan como **Triggers de Mutación de Estado** sobre el grafo de LangGraph y el motor de DuckDB, permitiendo la reconfiguración en caliente (on-the-fly) sin necesidad de reiniciar los procesos en PM2.

## 2. Catálogo de Comandos Core (Telegram Bot API)

### Módulo 1: Gestión de Identidad y Roles (Worker Factory)
Controla la asignación dinámica de plantillas y habilidades del agente.

*   **Comando:** `/role <worker_id>`
*   **Descripción:** Cambia el rol del agente en caliente (ej. `/role finanz` o `/role support`).
*   **Lógica Interna:**
    1.  Pausa el procesamiento de mensajes en el `thread_id` actual.
    2.  Invoca al `WorkerFactory` para cargar el `manifest.yaml` del nuevo rol.
    3.  Sobrescribe el `system_prompt` y el array de `tools` (Skills) en el estado global del grafo.
    4.  Emite un mensaje de confirmación con las nuevas capacidades adquiridas.

*   **Comando:** `/skills`
*   **Descripción:** Lista las herramientas (tools) actualmente habilitadas para el agente.
*   **Lógica Interna:**
    1.  Consulta el estado actual del nodo `Executor` en LangGraph.
    2.  Retorna un JSON/Markdown formateado con el nombre y descripción de cada herramienta (ej. `[SQLValidator, CategorizeExpense]`).

### Módulo 2: Control de Estado y Memoria (Habeas Data & Contexto)
Gestiona el *Checkpointer* de LangGraph y garantiza el derecho a la supresión de datos.

*   **Comando:** `/forget` (Reemplaza al tradicional `/clear`)
*   **Descripción:** Borra el historial de la conversación actual y reinicia el estado del grafo.
*   **Lógica Interna:**
    1.  Ejecuta un `DELETE` lógico o físico en la base de datos del *Checkpointer* de LangGraph para el `thread_id` asociado al `chat_id` de Telegram.
    2.  Libera la ventana de contexto del LLM local.
    3.  **Cumplimiento Legal:** Registra el evento de "Supresión de Datos Solicitada por el Usuario" en LangSmith para auditoría de Habeas Data.

*   **Comando:** `/context <on|off>`
*   **Descripción:** Activa o desactiva la inyección de memoria a largo plazo (RAG) en el prompt.
*   **Lógica Interna:**
    1.  Modifica un flag booleano `use_rag` en el estado del grafo.
    2.  Si es `off`, el nodo `Retriever` se omite (bypass) en el ciclo de LangGraph, forzando al agente a responder solo con su conocimiento paramétrico o el historial inmediato.

### Módulo 3: Auditoría y Transparencia (Observabilidad)
Expone métricas de ejecución y validación al usuario administrador.

*   **Comando:** `/audit`
*   **Descripción:** Muestra la evidencia cruda de la última acción ejecutada por el agente.
*   **Lógica Interna:**
    1.  Recupera el último `ExecutionResult` del estado de LangGraph.
    2.  Muestra la consulta SQL exacta generada, el tiempo de inferencia (ms) y el consumo de tokens.
    3.  Proporciona el `run_id` de LangSmith para trazabilidad forense.

*   **Comando:** `/health`
*   **Descripción:** Verifica el estado de la infraestructura subyacente.
*   **Lógica Interna:**
    1.  Ejecuta un ping al endpoint del servidor de inferencia local (MLX/llama.cpp).
    2.  Verifica el estado de conexión con `DuckDB`.
    3.  Retorna un reporte de latencia y uso de RAM/VRAM del VPS.

### Módulo 4: Intervención Humana (Human-in-the-Loop / HITL)
Comandos críticos para el flujo de aprobación de operaciones destructivas o sensibles.

*   **Comando:** `/approve` / `/reject`
*   **Descripción:** Autoriza o deniega una operación retenida por el `SQLValidator` o el `SandboxPipeline`.
*   **Lógica Interna:**
    1.  Requiere que el grafo de LangGraph esté en estado `interrupt` (pausado esperando input humano).
    2.  `/approve`: Reanuda el grafo pasando el estado al nodo `Executor` para aplicar el `INSERT`/`UPDATE` en DuckDB.
    3.  `/reject`: Enruta el grafo hacia el nodo `ErrorHandler`, indicando al LLM que la acción fue denegada por el usuario y debe replantear su estrategia.

## 3. Contrato de Implementación (Bot Handler)
El enrutador de comandos en `telegram_bot.py` debe implementarse como un middleware antes de invocar a LangGraph:

```python
# Especificación de enrutamiento
async def command_handler(message: Message, state: GraphState):
    if message.text.startswith("/"):
        command = parse_command(message.text)
        match command.name:
            case "role": return await execute_role_switch(command.args, state)
            case "forget": return await execute_memory_wipe(state.thread_id)
            case "approve": return await resume_graph_execution(state.thread_id, approved=True)
            # ...
    else:
        # Flujo normal hacia LangGraph
        return await langgraph_app.ainvoke({"messages": [message]}, config)
```

---

## 4. Implementación

| Componente | Ubicación |
|------------|-----------|
| **Parse y handlers** | `duckclaw/agents/on_the_fly_commands.py` |
| **Middleware en bot** | `duckclaw/agents/telegram_bot.py` (antes de saludos y LangGraph) |
| **Estado por chat** | `agent_config` con claves `chat_{chat_id}_worker_id`, `chat_{chat_id}_use_rag`, `chat_{chat_id}_last_audit` |

### Comandos implementados

| Comando | Descripción |
|---------|-------------|
| `/role <worker_id>` | Cambia el rol (plantilla Worker Factory). Ej: `/role finanz`, `/role support`. |
| `/skills` | Lista las herramientas actuales (del rol asignado o por defecto). |
| `/forget` | Borra el historial de la conversación y reinicia estado (Habeas Data). |
| `/context on\|off` | Activa/desactiva historial largo (más o menos mensajes en contexto). |
| `/prompt` \| `/prompt <texto>` | Muestra el system prompt actual o lo reemplaza por el nuevo texto (instrucción SYSTEM del grafo). |
| `/audit` | Muestra latencia y datos de la última ejecución (run_id si LangSmith está activo). |
| `/health` | Comprueba DuckDB y endpoint de inferencia (MLX). |
| `/approve` / `/reject` | HITL: mensaje informativo si el grafo no está en estado interrupt. |

### Flujo

1. Todo mensaje que empiece por `/` se parsea; si es un comando del catálogo, se ejecuta y se responde sin invocar LangGraph.
2. Si el chat tiene un `worker_id` asignado (`/role`), el siguiente mensaje usa `WorkerFactory().create(worker_id)` y ese grafo; si no, se usa el grafo por defecto (entry router).
3. Tras cada invocación exitosa se guarda `last_audit` (latencia, etc.) para `/audit`.
# Gestión de Ventana de Contexto (Memory Windowing)

## 1. Objetivo Arquitectónico
Definir la política y el contrato de **ventana de contexto** para el agente: qué porción del historial de conversación se inyecta en cada invocación del grafo, cómo se acota (por turnos, tokens o tiempo) y cómo se alinea con los límites del modelo y el derecho a supresión de datos (Habeas Data).

## 2. Fuentes de Contexto
El prompt enviado al LLM en cada turno se compone de:

| Fuente | Descripción | Persistencia |
|--------|-------------|--------------|
| **system_prompt** | Instrucción de rol (configurable con `/prompt` o `/setup`). | `agent_config.system_prompt` |
| **history** | Últimos N turnos usuario–asistente (mensajes + respuestas). | `telegram_conversation` (por `chat_id`) |
| **incoming** | Mensaje actual del usuario. | No persistido como historial hasta después de la respuesta. |

La ventana de contexto es el subconjunto de **history** que se incluye en la invocación; el resto del historial permanece en DuckDB pero no se envía al modelo.

## 3. Política Actual: Ventana por Turnos (Sliding Window)
*   **Métrica:** Número de **turnos** (pares user/assistant). No se cuenta tokens.
*   **Límite por defecto:** 10 turnos (20 mensajes) cuando `use_rag` está activo; 3 turnos (6 mensajes) cuando está desactivado (`/context off`).
*   **Criterio de selección:** Los **últimos N turnos** por `received_at` (sliding window). Los más antiguos fuera de la ventana no se envían al LLM.
*   **Exclusiones:** Mensajes cuyo texto empieza por `/` (comandos) no se incluyen en el historial inyectado.
*   **Persistencia:** Todo el historial se guarda en `telegram_conversation`; la ventana solo determina qué filas se leen para construir `state["history"]`.

### Contrato con el Grafo
*   **Estado de entrada:** `incoming` (str), `history` (list of `{"role": "user"|"assistant", "content": str}`).
*   **Origen de `history`:** `_get_history(chat_id, limit=history_limit)` donde `history_limit` viene de `get_history_limit_for_chat(db, chat_id)` (depende de `/context on|off`).

## 4. Comandos que Afectan la Ventana
| Comando | Efecto |
|---------|--------|
| `/context on` | Aumenta la ventana (p. ej. 10 turnos). Más memoria reciente en el prompt. |
| `/context off` | Reduce la ventana (p. ej. 3 turnos). Respuestas basadas solo en contexto reciente. |
| `/forget` | Borra todo el historial del chat en `telegram_conversation` y reinicia la ventana efectiva (Habeas Data). |

## 5. Límites por Tokens (Futuro)
Para modelos con tope de contexto (ej. 4K/8K tokens), se puede extender la política con:

*   **Límite por tokens:** Estimar tokens por mensaje (p. ej. ~4 por palabra o uso de tiktoken) y truncar `history` hasta no superar un `max_context_tokens` (reservando espacio para system_prompt + incoming + respuesta).
*   **Estrategias:** (a) Cortar los mensajes más antiguos; (b) Resumir turnos antiguos con un paso de summarization y enviar solo el resumen + ventana reciente.
*   **Configuración:** Parámetro por worker o global, p. ej. `max_history_tokens` en `manifest.yaml` o `agent_config`.

## 6. Retención y Habeas Data
*   **Retención:** El historial en `telegram_conversation` no tiene purga automática por fecha; crece indefinidamente por chat hasta que el usuario ejecuta `/forget` o se implemente una política de retención (p. ej. borrar mensajes mayores a X días).
*   **Supresión:** `/forget` realiza un `DELETE FROM telegram_conversation WHERE chat_id = ?`, cumpliendo la solicitud de supresión del usuario (auditable en LangSmith si está activo).
*   **Aislamiento:** La ventana se calcula por `chat_id`; un chat no accede al historial de otro.

## 7. Especificación de Módulos (Referencia)
| Componente | Ubicación | Responsabilidad |
|------------|-----------|------------------|
| **Límite de ventana** | `on_the_fly_commands.get_history_limit_for_chat()` | Devuelve 3 o 10 según `use_rag`. |
| **Lectura del historial** | `telegram_bot._get_history(chat_id, limit)` | Últimos `limit` turnos desde `telegram_conversation`. |
| **Persistencia** | `telegram_bot._persist_conversation()` | Inserta cada turno en `telegram_conversation`. |
| **Borrado** | `on_the_fly_commands.execute_forget()` | DELETE por `chat_id` y limpieza de `last_audit`. |

## 8. Resumen
La ventana de contexto es **sliding por turnos**, configurable con `/context on|off` y con supresión total mediante `/forget`. La persistencia es en DuckDB (`telegram_conversation`); la inyección en el grafo es el subconjunto reciente definido por `history_limit`. Una extensión futura puede añadir límites por tokens y summarization para modelos con contexto acotado.

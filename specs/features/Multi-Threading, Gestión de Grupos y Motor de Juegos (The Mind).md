# Multi-Threading, Gestión de Grupos y Motor de Juegos (The Mind)

## 1. Objetivo Arquitectónico
Evolucionar el API Gateway y el motor de LangGraph para soportar contextos multi-usuario dentro de un mismo `thread_id` (Grupo). Implementar bloqueos de concurrencia (Mutex) para evitar corrupción de estado, inyección de identidad en los prompts, y un sistema de enrutamiento cruzado (Cross-Routing) que permita al agente escuchar en un grupo y responder por mensaje directo (DM) a usuarios específicos.

## 2. Evolución del Contrato API (Multi-User Payload)

El Gateway debe saber *quién* habla dentro del grupo. El equipo de n8n debe actualizar el webhook para enviar estos nuevos campos.

```python
# services/api-gateway/core/models.py
class ChatRequest(BaseModel):
    message: str
    chat_id: str           # ID del Grupo (ej. -100123456) o del DM
    user_id: str           # ID único del usuario que envió el mensaje
    username: str          # Nombre del usuario (ej. "Juan")
    chat_type: str         # "private", "group", "supergroup"
```

## 3. Gestión de Concurrencia (Group Thread-Safety)

Si tres personas escriben al mismo tiempo en un grupo de Telegram, LangGraph intentará actualizar el mismo `thread_id` simultáneamente, causando un *State Conflict*.

*   **Solución (Redis Mutex):**
    En el `ActivityManager` (o antes de encolar en ARQ), implementamos un bloqueo por `chat_id`.
    ```python
    # Pseudo-código en el consumidor de ARQ
    async def process_message(ctx, payload):
        lock_key = f"lock:chat:{payload.chat_id}"
        # Esperar hasta que el chat esté libre (procesamiento secuencial estricto por grupo)
        async with redis.lock(lock_key, timeout=10, blocking_timeout=15):
            await agent.ainvoke(...)
    ```

## 4. Inyección de Identidad (Contexto Multi-Usuario)

El LLM debe saber quién dice qué para no confundir a los usuarios.

*   **Lógica en `graph_server.py`:**
    Antes de pasar el mensaje a LangGraph, el Gateway formatea el contenido del `HumanMessage`:
    ```python
    if payload.chat_type in ["group", "supergroup"]:
        formatted_content = f"[{payload.username}]: {payload.message}"
    else:
        formatted_content = payload.message
        
    # El LLM verá: "[Juan]: Juego el 15" o "[Carlos]: ¡Cuidado!"
    ```

## 5. Enrutamiento Cruzado (Cross-Routing para DMs)

Para "The Mind", el agente (Crupier) debe repartir cartas en secreto. No puede hacerlo en el grupo.

*   **Especificación de Skill: `SendPrivateMessage`**
    *   El agente invoca esta herramienta para susurrarle a un jugador.
    *   **Contrato:** `send_dm(user_id: str, text: str)`
    *   **Implementación:** Llama a un webhook especial en n8n (`/webhook/send-dm`) que usa el nodo de Telegram configurado para enviar al `user_id` en lugar del `chat_id` del grupo.

## 6. Especificación del Motor de Juego: `TheMindCrupier`

Para juegos donde la latencia es crítica (milisegundos), **no usaremos el LLM para validar las jugadas**. Usaremos **Fly Commands** interceptados por el Gateway, y dejaremos al LLM solo para la "personalidad" del Crupier.

### A. Esquema de Base de Datos (DuckDB)
```sql
CREATE TABLE the_mind_games (
    chat_id VARCHAR PRIMARY KEY,
    level INTEGER DEFAULT 1,
    lives INTEGER,
    shurikens INTEGER,
    cards_played INTEGER[]
);

CREATE TABLE the_mind_hands (
    chat_id VARCHAR,
    user_id VARCHAR,
    username VARCHAR,
    cards INTEGER[],
    PRIMARY KEY (chat_id, user_id)
);
```

### B. Fly Commands del Juego (Ejecución en < 50ms)

Estos comandos se procesan en `on_the_fly_commands.py` (bypasseando LangGraph):

1.  **/start_mind**
    *   Limpia las tablas para ese `chat_id`.
    *   Asigna vidas (ej. 3).
2.  **/deal** (Repartir)
    *   Genera números aleatorios (1-100).
    *   Guarda en `the_mind_hands`.
    *   Ejecuta `send_dm` (vía n8n) a cada `user_id` con sus cartas.
    *   Responde en el grupo: *"Cartas repartidas por DM. ¡Que comience el Nivel X! 🤫"*
3.  **/play `<numero>`** (Ej. `/play 15`)
    *   **Validación Atómica:**
        *   ¿El usuario tiene el 15? (Si no, ignorar).
        *   ¿Alguien más tiene una carta `< 15`?
            *   *Sí (Error):* Restar vida. Eliminar cartas `< 15` de todas las manos. Anunciar: *"❌ ¡ERROR! @{username} jugó {numero}, pero alguien tenía una menor. Pierden 1 vida."*
            *   *No (Éxito):* Mover 15 a `cards_played`. Anunciar: *"✅ @{username} jugó el {numero}."*
    *   **Check de Victoria:** Si todas las manos están vacías (`cards =

# Motor de Juego The Mind (Multi-Channel)

## 1. Esquema de Base de Datos (DuckDB)
Ejecutar este DDL en la base de datos del Gateway para mantener el estado de las partidas.

```sql
CREATE TABLE IF NOT EXISTS the_mind_games (
    game_id VARCHAR PRIMARY KEY,
    status VARCHAR DEFAULT 'waiting', -- waiting, playing, won, lost
    current_level INTEGER DEFAULT 1,
    lives INTEGER DEFAULT 3,
    shurikens INTEGER DEFAULT 1,
    cards_played INTEGER[] DEFAULT[]
);

CREATE TABLE IF NOT EXISTS the_mind_players (
    game_id VARCHAR REFERENCES the_mind_games(game_id),
    chat_id VARCHAR,
    username VARCHAR,
    cards INTEGER[] DEFAULT[],
    PRIMARY KEY (game_id, chat_id)
);
```

## 2. Módulo de Comunicación Outbound (El Megáfono)
Crear un archivo de utilidades para que el Gateway pueda disparar mensajes a n8n sin esperar al LLM.

*   **Ubicación:** `packages/agents/src/duckclaw/utils/outbound.py`
```python
import httpx
import os

async def send_dm(chat_id: str, text: str):
    """Envía un mensaje directo vía el flujo Outbound de n8n."""
    url = os.getenv("N8N_OUTBOUND_WEBHOOK_URL") # Ej: https://n8n.../webhook/duckclaw-outbound
    headers = {"X-DuckClaw-Secret": os.getenv("N8N_AUTH_KEY")}
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"chat_id": chat_id, "text": text}, headers=headers)

async def broadcast_to_game(db_conn, game_id: str, text: str):
    """Envía un mensaje a todos los jugadores de una partida."""
    players = db_conn.execute("SELECT chat_id FROM the_mind_players WHERE game_id = ?", [game_id]).fetchall()
    for (chat_id,) in players:
        await send_dm(chat_id, text)
```

## 3. Lógica del Motor de Juego (Fly Commands)
Interceptar estos comandos en `services/api-gateway/main.py` (o en tu módulo de `on_the_fly_commands.py`) **antes** de invocar a LangGraph.

### A. `/new_mind` (Crear Partida)
1.  Generar un ID corto (ej. `MIND-123`).
2.  `INSERT INTO the_mind_games (game_id) VALUES ('MIND-123')`.
3.  `INSERT INTO the_mind_players` (Añadir al creador).
4.  **Respuesta:** *"Partida creada. Dile a tus amigos que me envíen `/join MIND-123` por mensaje privado."*

### B. `/join <game_id>` (Unirse)
1.  Verificar que el juego existe y está en `waiting`.
2.  `INSERT INTO the_mind_players`.
3.  **Broadcast:** *"@{username} se ha unido a la partida."*

### C. `/start_mind <game_id>` (Repartir Cartas)
1.  Actualizar estado a `playing`.
2.  Calcular cartas necesarias (Nivel 1 = 1 carta por jugador).
3.  Generar números aleatorios únicos (1-100).
4.  Actualizar la columna `cards` de cada jugador en `the_mind_players`.
5.  **Bucle de DMs:** Para cada jugador, llamar a `send_dm(chat_id, f"Tus cartas para el Nivel 1 son: {sus_cartas}")`.
6.  **Broadcast:** *"¡El Nivel 1 ha comenzado! Concéntrense... 🤫"*

### D. `/game` (Listar partidas activas)

Listar partidas con `status` en `waiting` o `playing`, con conteo de jugadores y metadatos (`current_level`, `lives`). Implementado en `execute_list_mind_games` (`on_the_fly_commands.py`).

### E. Backlog de reglas (no implementado aún)

- **Shurikens:** la columna `shurikens` existe en `the_mind_games` pero no hay comando `/shuriken` ni consumo del contador; pendiente alinear con reglas oficiales (revelar mínimo en mano, etc.).
- **Tras perder una vida:** el motor actual descarta cartas menores y continúa el mismo nivel; valorar si el diseño deseado es **repartir de nuevo** el nivel actual (reglas de mesa).

### F. `/play <numero>` (El Bucle Crítico)
*Esta es la transacción atómica que define el juego.*

```python
async def handle_play_card(db_conn, chat_id: str, username: str, played_card: int):
    # 1. Obtener el game_id del jugador
    game_id = db_conn.execute("SELECT game_id FROM the_mind_players WHERE chat_id = ?", [chat_id]).fetchone()[0]
    
    # 2. Verificar si el jugador tiene la carta
    # (Lógica SQL para verificar si played_card está en el array 'cards')
    
    # 3. Verificar si ALGUIEN tiene una carta MENOR
    lowest_card_query = """
        SELECT MIN(unnest(cards)) FROM the_mind_players WHERE game_id = ?
    """
    lowest_card = db_conn.execute(lowest_card_query, [game_id]).fetchone()[0]
    
    if played_card > lowest_card:
        # ❌ ERROR: Alguien tenía una carta menor
        db_conn.execute("UPDATE the_mind_games SET lives = lives - 1 WHERE game_id = ?",[game_id])
        # Eliminar todas las cartas menores a played_card de todas las manos (Lógica de castigo)
        await broadcast_to_game(db_conn, game_id, f"❌ ¡ERROR! @{username} jugó el {played_card}, pero alguien tenía el {lowest_card}. Pierden 1 vida.")
    else:
        # ✅ ÉXITO: Era la carta correcta
        # Eliminar la carta de la mano del jugador y añadirla a cards_played
        await broadcast_to_game(db_conn, game_id, f"✅ @{username} jugó el {played_card}.")
        
    # 4. Verificar si el nivel terminó (todas las manos vacías)
    # Si terminó -> Subir nivel, repartir nuevas cartas (Llamar a la lógica de /start_mind para el sig. nivel).
```

## 4. Configuración en n8n (Requisito)
Asegúrate de que el equipo de integraciones tenga este flujo activo en el VPS:
1.  **Webhook:** `POST /webhook/duckclaw-outbound` (Con Header Auth `X-DuckClaw-Secret`).
2.  **Telegram Node:** Operation `Send Message`.
    *   Chat ID: `{{ $json.body.chat_id }}`
    *   Text: `{{ $json.body.text }}`
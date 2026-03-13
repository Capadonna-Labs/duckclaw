# services/db-writer/main.py
import asyncio
import json
import logging
import duckdb
import redis.asyncio as redis
from core.config import settings

# Configuración de logging robusto
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("db-writer")

async def process_queue():
    """Bucle principal que consume la cola de Redis y escribe en DuckDB."""
    
    # 1. Conexión a Redis
    redis_client = redis.from_url(str(settings.REDIS_URL), decode_responses=True)
    
    # 2. Conexión a DuckDB (Modo READ_WRITE)
    try:
        conn = duckdb.connect(settings.DUCKDB_PATH, read_only=False)
        logger.info(f"Conectado a DuckDB en: {settings.DUCKDB_PATH}")
    except Exception as e:
        logger.critical(f"Error fatal conectando a DuckDB: {e}")
        return

    logger.info(f"Escuchando la cola de Redis: {settings.QUEUE_NAME}...")

    try:
        while True:
            # 3. Lectura Bloqueante (BRPOP)
            result = await redis_client.brpop(settings.QUEUE_NAME, timeout=0)
            
            if result:
                _, message = result
                await execute_write(conn, message)
                
    except asyncio.CancelledError:
        logger.info("Señal de apagado recibida. Cerrando conexiones...")
    finally:
        # 4. Limpieza (Graceful Shutdown)
        conn.close()
        await redis_client.aclose()
        logger.info("DB Writer apagado correctamente.")

async def execute_write(conn: duckdb.DuckDBPyConnection, message: str):
    """Ejecuta la consulta SQL de forma segura."""
    try:
        payload = json.loads(message)
        task_id = payload.get("task_id", "unknown")
        query = payload.get("query")
        params = payload.get("params",[]) # <-- Línea completada

        if not query:
            logger.warning(f"[{task_id}] Payload inválido: No hay query SQL.")
            return

        # Ejecutar la consulta en un hilo separado para no bloquear el Event Loop
        await asyncio.to_thread(conn.execute, query, params)
        
        logger.info(f"[{task_id}] Escritura exitosa: {query[:60]}...")

    except json.JSONDecodeError:
        logger.error("Error decodificando el mensaje de Redis. Formato JSON inválido.")
    except duckdb.Error as e:
        logger.error(f"[{task_id}] Error de DuckDB ejecutando la query: {e}")
        # TODO futuro: Enviar el payload fallido a una Dead Letter Queue (DLQ) en Redis
    except Exception as e:
        logger.error(f"[{task_id}] Error inesperado: {e}")

if __name__ == "__main__":
    logger.info("Iniciando DuckClaw DB Writer...")
    try:
        asyncio.run(process_queue())
    except KeyboardInterrupt:
        logger.info("Proceso detenido por el usuario (KeyboardInterrupt).")
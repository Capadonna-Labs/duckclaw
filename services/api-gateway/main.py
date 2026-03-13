# services/api-gateway/main.py
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import redis.asyncio as redis
import json
import uuid
from contextlib import asynccontextmanager

# Importamos la configuración validada
from core.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Usamos settings.REDIS_URL (ya validado por Pydantic como un RedisDsn)
    # Convertimos a string porque redis.from_url espera un string
    app.state.redis = redis.from_url(str(settings.REDIS_URL), decode_responses=True)
    yield
    await app.state.redis.aclose()

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION, lifespan=lifespan)

# 2. Modelos de Datos (DTOs)
class WriteRequest(BaseModel):
    query: str = Field(..., description="Consulta SQL parametrizada (ej. INSERT INTO tabla VALUES (?))")
    params: list = Field(default_factory=list, description="Lista de parámetros para la consulta")
    tenant_id: str = Field(default="default", description="ID del espacio de trabajo")

class EnqueueResponse(BaseModel):
    status: str
    task_id: str

# 3. Endpoints
@app.get("/health")
async def health():
    return {"status": "ok", "service": "api-gateway"}

@app.post("/api/v1/db/write", response_model=EnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_write(req: WriteRequest):
    """
    Encola una operación de escritura (INSERT/UPDATE/DELETE) para ser procesada
    secuencialmente por el db-writer, evitando bloqueos en DuckDB.
    """
    # Validación básica de seguridad (Prevenir SELECTs en la cola de escritura)
    if req.query.strip().upper().startswith("SELECT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Las consultas SELECT deben ejecutarse directamente, no encolarse."
        )

    task_id = str(uuid.uuid4())
    
    # Construir el payload estructurado
    payload = {
        "task_id": task_id,
        "tenant_id": req.tenant_id,
        "query": req.query,
        "params": req.params
    }
    
    try:
        # Encolar asíncronamente en la lista de Redis
        await app.state.redis.lpush("duckdb_write_queue", json.dumps(payload))
        return EnqueueResponse(status="enqueued", task_id=task_id)
    except redis.RedisError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Error conectando al broker de mensajes: {str(e)}"
        )
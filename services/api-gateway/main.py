from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis
import os

app = FastAPI(title="DuckClaw API Gateway")

class QueryRequest(BaseModel):
    sql: str

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
r = redis.from_url(redis_url)
queue_key = "duckdb_write_queue"

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/api/v1/execute")
async def execute_sql(req: QueryRequest):
    # Enqueue write operation
    r.rpush(queue_key, req.sql)
    return {"status": "enqueued"}

# Note: Read operations would be direct using a DuckClaw instance (multi-reader allowed)

# services/db-writer/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import RedisDsn
from pathlib import Path

# Calcula la raíz del monorepo (sube 3 niveles: core -> db-writer -> services -> duckclaw)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent

class Settings(BaseSettings):
    PROJECT_NAME: str = "DuckClaw DB Writer"
    REDIS_URL: RedisDsn = "redis://localhost:6379/0"
    QUEUE_NAME: str = "duckdb_write_queue"
    
    # Ruta absoluta calculada dinámicamente
    DUCKDB_PATH: str = str(ROOT_DIR / "db" / "duckclaw.duckdb") 

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
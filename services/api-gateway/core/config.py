# services/api-gateway/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import RedisDsn

class Settings(BaseSettings):
    # Configuración de la API
    PROJECT_NAME: str = "DuckClaw API Gateway"
    VERSION: str = "0.0.1"
    
    # Configuración de Redis (Valida automáticamente que sea una URL válida de Redis)
    REDIS_URL: RedisDsn = "redis://localhost:6379/0"
    
    # Configuración de Seguridad (valores por defecto para desarrollo/local; en producción definir en .env)
    JWT_SECRET: str = "dev-secret-change-in-production"
    N8N_AUTH_KEY: str = "dev-n8n-auth-key"

    # Le dice a Pydantic que lea del archivo .env si existe (útil para desarrollo local)
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

# Instancia global (Singleton)
settings = Settings()
# API Gateway Hardening & Open-Source Readiness

## 1. Objetivo Arquitectónico
Evolucionar el `services/api-gateway` de un prototipo funcional a un **Gateway de Grado Producción, Seguro y Multiplataforma**. Al ser un proyecto Open Source, el Gateway debe ser agnóstico al sistema operativo (macOS, Linux, Windows), fácil de configurar mediante variables de entorno validadas, y venir con defensas preconfiguradas (Rate Limiting, CORS estricto, Dual Auth) para que cualquier usuario pueda exponerlo a internet (vía Cloudflare o Tailscale) sin riesgo de compromiso.

## 2. Gestión de Configuración (Pydantic Settings)
Eliminar el uso de `os.getenv` disperso por el código. Implementar una clase centralizada que valide el entorno al arrancar. Si falta una variable crítica, el Gateway no debe arrancar (Fail-Fast).

*   **Ubicación:** `services/api-gateway/core/config.py`
*   **Lógica:**
    ```python
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class GatewaySettings(BaseSettings):
        # Core
        ENVIRONMENT: str = "production" # dev, prod, test
        API_V1_STR: str = "/api/v1"
        
        # Security
        SECRET_KEY: str # Obligatorio para firmar JWTs
        N8N_AUTH_KEY: str # Obligatorio para webhooks internos
        ALLOWED_ORIGINS: list[str] =["http://localhost:4200"] # CORS
        
        # Rate Limiting
        RATE_LIMIT_PER_MINUTE: int = 60

        model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    settings = GatewaySettings()
    ```

## 3. Capas de Seguridad (Middlewares & Interceptors)

El Gateway debe implementar un patrón de "Cebolla" (Onion Routing) para la seguridad.

### A. Capa 1: CORS & Security Headers
*   **CORS:** Restringido estrictamente a `ALLOWED_ORIGINS`. No usar `["*"]` en producción.
*   **Headers:** Implementar un middleware que inyecte cabeceras de seguridad (HSTS, X-Content-Type-Options, X-Frame-Options).

### B. Capa 2: Rate Limiting (Protección DoS)
*   **Tecnología:** `slowapi` (basado en memoria para un solo nodo, o Redis si se usa el `ActivityManager`).
*   **Reglas:**
    *   Endpoints públicos (`/health`): 100 req/min.
    *   Endpoints de inferencia (`/chat`): 20 req/min por IP/Usuario.

### C. Capa 3: Autenticación Dual (Dual Auth Strategy)
El Gateway debe soportar dos clientes principales con diferentes métodos de autenticación:
1.  **Frontend (Angular):** Autenticación basada en **JWT** (`Authorization: Bearer <token>`).
2.  **Orquestador (n8n/Servicios):** Autenticación basada en **API Key estática** (`X-API-Key: <N8N_AUTH_KEY>`).

*   **Implementación (FastAPI Dependency):**
    ```python
    from fastapi import Security, HTTPException, status
    from fastapi.security import APIKeyHeader, HTTPBearer

    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
    jwt_bearer = HTTPBearer(auto_error=False)

    async def verify_access(api_key: str = Security(api_key_header), jwt: str = Security(jwt_bearer)):
        if api_key and api_key == settings.N8N_AUTH_KEY:
            return "service_account"
        if jwt and validate_jwt(jwt.credentials):
            return "user_account"
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Acceso denegado")
    ```

## 4. Estandarización de Respuestas y Errores (RFC 7807)
Para que n8n y Angular puedan manejar errores de forma predecible, el Gateway debe capturar todas las excepciones y devolver un formato estándar (Problem Details for HTTP APIs).

*   **Formato de Error:**
    ```json
    {
      "type": "https://duckclaw.dev/errors/rate-limit",
      "title": "Too Many Requests",
      "status": 429,
      "detail": "Has excedido el límite de 20 mensajes por minuto.",
      "instance": "/api/v1/agent/finanz/chat"
    }
    ```

## 5. Cross-Platform Readiness (El "Developer Experience")

Para que un usuario en Windows, Linux o macOS pueda levantar el Gateway sin fricción:

### A. Agnosticismo de Hardware en el Gateway
El `api-gateway` **no debe importar `mlx` directamente**. MLX es exclusivo de Apple Silicon. El Gateway debe comunicarse con el motor de inferencia a través de interfaces abstractas (definidas en `packages/shared/`). Si el usuario está en Windows/Linux, el Gateway enrutará la petición a `llama.cpp` o a una API externa (Groq/OpenAI) según la configuración, sin fallar en tiempo de importación.

### B. CLI de Inicialización (`duckops`)
Añadir comandos al CLI para facilitar el *onboarding* de nuevos usuarios open-source:
*   `uv run duckops init`: Genera el `.env` con claves criptográficas seguras automáticamente (`openssl rand -hex 32`).
*   `uv run duckops serve --gateway`: Levanta el servidor Uvicorn detectando el SO automáticamente.

## 6. Contrato de Integración (Endpoints Core)

El Gateway expondrá los siguientes endpoints estabilizados:

| Método | Endpoint | Auth Requerida | Consumidor Principal |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Ninguna | Load Balancers, n8n |
| `POST` | `/api/v1/chat/stream` | JWT / API Key | Angular (SSE) |
| `POST` | `/api/v1/webhook/n8n` | API Key | n8n (Eventos asíncronos) |
| `GET` | `/api/v1/system/status` | JWT (Admin) | Angular (Dashboard) |
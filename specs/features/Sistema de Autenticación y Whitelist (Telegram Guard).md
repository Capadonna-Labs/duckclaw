# Sistema de Autenticación y Whitelist (Telegram Guard)

## 1. Objetivo Arquitectónico
Implementar una capa de seguridad perimetral en el **API Gateway** que valide la identidad de los usuarios de Telegram antes de permitir cualquier interacción con los agentes. Este sistema garantiza el cumplimiento de **Habeas Data** al prevenir el acceso no autorizado a bases de datos financieras y protege los recursos de cómputo (Mac Mini / GPUs) de ataques de denegación de servicio o uso indebido.

## 2. Especificación de Persistencia (Whitelist Store)

Utilizaremos un enfoque híbrido: **DuckDB** como fuente de verdad persistente y **Redis** como caché de alta velocidad para validación en tiempo real.

### A. Esquema DuckDB (Tabla Maestra)
Se debe añadir esta tabla al esquema `main` de la base de datos global.
```sql
CREATE TABLE IF NOT EXISTS authorized_users (
    tenant_id VARCHAR,           -- ID del cliente (ej. 'powerseal', 'admin')
    user_id VARCHAR,             -- ID de Telegram del usuario
    username VARCHAR,            -- Alias de Telegram para auditoría
    role VARCHAR DEFAULT 'user', -- 'admin' (puede usar /team) o 'user'
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, user_id)
);
```

### A.1 Bases compartidas (ACL por usuario)

Tabla **`main.user_shared_db_access`**: define qué `resource_key` de catálogo compartido puede usar cada `(tenant_id, user_id)` además del sandbox de rutas (`validate_user_db_path`).

```sql
CREATE TABLE IF NOT EXISTS main.user_shared_db_access (
    tenant_id VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    resource_key VARCHAR NOT NULL,  -- 'default' → DUCKCLAW_SHARED_DB_PATH; '*' → comodín; otro → DUCKCLAW_SHARED_RESOURCE_<KEY>
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, user_id, resource_key)
);
```

- **Sin filas** para un usuario: compatibilidad — basta con ruta válida bajo `db/shared/`.
- **Con una o más filas**: debe existir `*` o un `resource_key` cuya ruta resuelta coincida con el `.duckdb` compartido solicitado.

Gestión vía **`/team --shared-list`**, **`--shared-grant`**, **`--shared-revoke`** (solo `role=admin`). El gateway y el db-writer consultan esta tabla antes de usar `DUCKCLAW_SHARED_DB_PATH` / `shared_db_path` / escrituras bajo `db/shared/`.

### B. Estructura en Redis (Caché de Validación)
*   **Key:** `whitelist:{tenant_id}:{user_id}`
*   **Value:** `role` (string)
*   **TTL:** 1 hora (para forzar sincronización con DuckDB periódicamente).

## 3. Especificación del Interceptor (API Gateway)

El chequeo debe ocurrir en `services/api-gateway/main.py` inmediatamente después de resolver el `tenant_id` y antes de cualquier lógica de LangGraph.

*   **Lógica de Validación:**
    1.  Extraer `user_id` y `tenant_id` del payload entrante.
    2.  **Check 1 (Bypass):** Si el `user_id` es el del dueño del sistema (definido en `.env`), permitir siempre.
    3.  **Check 2 (Redis):** Buscar la clave en Redis. Si existe, permitir.
    4.  **Check 3 (DuckDB):** Si no está en Redis, consultar DuckDB.
        *   Si existe: Cargar en Redis y permitir.
        *   Si no existe: **Bloquear**.

*   **Contrato de Rechazo:**
    *   HTTP Status: `403 Forbidden`.
    *   Response Body: `{"detail": "Acceso denegado. No tienes autorización para interactuar con este agente."}`.

## 4. Gestión de Accesos: Fly Command `/team`

Este comando permite la gestión dinámica de la whitelist desde el chat de Telegram, sin tocar la base de datos manualmente.

*   **Sintaxis:**
    *   `/team`: Lista los usuarios autorizados en el chat actual.
    *   `/team --add <user_id> [username]`: Añade un usuario a la whitelist del tenant actual.
    *   `/team --rm <user_id>`: Elimina un usuario de la whitelist.

*   **Restricción de Seguridad:**
    *   Solo usuarios con `role == 'admin'` en la tabla `authorized_users` pueden ejecutar las variantes `--add` y `--rm`.

## 5. Auditoría y Forense (Security Logs)

Cada intento de acceso debe ser registrado para cumplir con la normativa colombiana de protección de datos.

*   **Log de Éxito:** Registrar en LangSmith con el tag `auth_status: authorized`.
*   **Log de Rechazo:**
    1.  Emitir un log de nivel `WARNING` en PM2: `[SECURITY_ALERT] Unauthorized access attempt: user_id='X' tenant_id='Y'`.
    2.  Registrar en LangSmith con el tag `auth_status: unauthorized_attempt`.
    3.  (Opcional) n8n: Disparar una alerta al Telegram del administrador si un mismo `user_id` intenta acceder más de 3 veces sin éxito.

## 6. Guía de pruebas (Smoke)

### 6.1. Confirmar que el esquema existe
En DuckDB (mismo DB que usa el Gateway; por defecto `db/finanzdb1.duckdb`):
```sql
SELECT * FROM main.authorized_users;
```
Si falla porque no existe la tabla, reinicia el gateway para que ejecute la inicialización (idempotente).

### 6.2. Preparar un usuario autorizado (ejemplo)
Inserta un usuario para un `tenant_id`:
```sql
INSERT INTO main.authorized_users (tenant_id, user_id, username, role)
VALUES ('default', '123', 'bot_test_user', 'user')
ON CONFLICT (tenant_id, user_id) DO UPDATE SET
  username = EXCLUDED.username,
  role = EXCLUDED.role,
  updated_at = CURRENT_TIMESTAMP;
```

### 6.3. Probar rechazo (403) para usuario NO autorizado
Ejemplo:
```bash
curl -sS -X POST "http://localhost:8000/api/v1/agent/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "/help",
    "chat_id": "test_chat_001",
    "user_id": "999999",
    "username": "unauthorized",
    "chat_type": "private",
    "tenant_id": "default",
    "history": [],
    "stream": false
  }'
```

Verificación:
- Respuesta HTTP esperada: `403 Forbidden`.
- En PM2 debe aparecer:
  - `[SECURITY_ALERT] Unauthorized access attempt: user_id='999999' tenant_id='default'`

### 6.4. Probar bypass del dueño del sistema (admin/owner)
El bypass se basa en `DUCKCLAW_OWNER_ID` (si existe) o en `DUCKCLAW_ADMIN_CHAT_ID`.

Ejemplo:
```bash
curl -sS -X POST "http://localhost:8000/api/v1/agent/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "/sandbox on",
    "chat_id": "test_chat_bypass",
    "user_id": "1726618406",
    "username": "admin_bypass",
    "chat_type": "private",
    "tenant_id": "default",
    "history": [],
    "stream": false
  }'
```

Verificación:
- Respuesta HTTP: `200`.
- Si luego ejecutas un request donde el usuario autorizado/permitido dispare `run_sandbox`, el sandbox debe estar ON para `chat_id=test_chat_bypass` (estado por sesión).

### 6.5. Probar que un usuario autorizado pasa
Ejemplo (para `user_id=123` role `user`):
```bash
curl -sS -X POST "http://localhost:8000/api/v1/agent/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "/sandbox on",
    "chat_id": "test_chat_authorized",
    "user_id": "123",
    "username": "bot_test_user",
    "chat_type": "private",
    "tenant_id": "default",
    "history": [],
    "stream": false
  }'
```

Verificación:
- Respuesta HTTP: `200`.
- No debe aparecer `[SECURITY_ALERT]` para ese request.

### 6.6. Probar alerta al admin (3 rechazos)
Si está configurado:
- `DUCKCLAW_ADMIN_CHAT_ID=1726618406`
- `N8N_OUTBOUND_WEBHOOK_URL`
- (opcional) `N8N_AUTH_KEY`

Envía 3 veces seguidas un request **no autorizado** (paso 6.3) con el mismo `tenant_id` y `user_id`.

Verificación:
- En PM2 verás 3 warnings `[SECURITY_ALERT] ...`.
- En logs del gateway puede aparecer `error enviando alerta webhook` si el webhook no está configurado; si sí está, debe dispararse el POST al webhook.

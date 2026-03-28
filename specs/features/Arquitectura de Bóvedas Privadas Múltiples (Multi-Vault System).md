# Arquitectura de Bóvedas Privadas Múltiples (Multi-Vault System)

## 1. Objetivo Arquitectónico
Evolucionar el sistema de persistencia para permitir que un único usuario gestione múltiples bases de datos privadas independientes (ej. "Finanzas Personales", "Inversiones", "Proyectos Secretos"). El sistema debe permitir la creación, listado y conmutación en caliente (Hot-Swapping) de estas bóvedas, garantizando que el agente siempre trabaje sobre el contexto de datos correcto mediante el alias dinámico `private` en DuckDB.

## 2. Modelo de Metadatos (System Registry)

Para gestionar la relación Usuario-Bóvedas, la base de datos `system.duckdb` debe incorporar un registro de propiedad:

```sql
-- Tabla de registro de bóvedas
CREATE TABLE IF NOT EXISTS user_vaults (
    user_id VARCHAR,             -- ID de Telegram / UUID
    vault_id VARCHAR,           -- ID único del archivo (ej. 'finanzas_abc')
    vault_name VARCHAR,         -- Nombre amigable (ej. 'Gastos 2026')
    is_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, vault_id)
);
```

## 3. Topología de Archivos (Hierarchical Storage)

Los archivos se organizarán por carpetas de usuario para facilitar backups granulares:

```text
db/
├── system.duckdb
├── private/
│   └── {user_id}/              # Una carpeta por usuario; varios .duckdb (vault_id)
│       ├── default.duckdb
│       ├── inversiones.duckdb
│       └── trabajo.duckdb
└── shared/
    ├── {user_id}/              # Compat: mismas rutas que slug de usuario (p. ej. catálogo por chat)
    │   └── leiladb1.duckdb
    └── {tenant_id}/            # Datos compartidos del tenant (slug sanitizado; p. ej. leila_store)
        └── catalogo.duckdb
```

`validate_user_db_path` en `duckclaw.vaults` autoriza escrituras solo si el `.duckdb` cae bajo `private/{user_id}/`, `shared/{user_id}/` o `shared/{tenant_id}/` (este último solo cuando el payload incluye el mismo `tenant_id` efectivo que en la petición autorizada).

## 4. Especificación de Skill: `VaultManager`

Esta skill permite al usuario (y al agente) manipular su ecosistema de datos.

*   **Operaciones:**
    1.  `create_vault(name)`: Crea un nuevo archivo `.duckdb` e inicializa el esquema base.
    2.  `list_vaults()`: Consulta `user_vaults` para mostrar las opciones disponibles.
    3.  `switch_vault(vault_id)`: 
        *   Actualiza `is_active` en la tabla `user_vaults`.
        *   Notifica al Gateway para reiniciar la sesión del agente con el nuevo `ATTACH`.

## 5. Lógica de Conexión Dinámica (Forge / DynamicContext)

La resolución de rutas ocurre en `build_worker_graph` (`packages/agents/.../workers/factory.py`):

1.  **Bóveda activa (HTTP/Gateway):** el `vault_db_path` llega desde `resolve_active_vault(user_id)` o equivalente dedicado.
2.  **Contexto dual (opcional):** si el `manifest.yaml` declara `forge_context.shared_db_path_env`, se lee esa variable de entorno y se ejecuta un segundo `ATTACH ... AS shared`. La petición puede sobrescribir con `shared_db_path` en el body del chat.
3.  **Inyección SQL (best-effort):**
    ```sql
    DETACH private;  -- si aplica
    ATTACH '<vault_db_path>' AS private;
    DETACH shared;
    ATTACH '<shared_duckdb>' AS shared;  -- solo si la ruta compartida está resuelta y distinta de la privada
    ```
    Las herramientas `read_sql` del worker reintentan calificando tablas con `main`, `private` y `shared` cuando hay allow-list.

## 6. Interfaz de Control: Fly Command `/vault`

Se implementa un nuevo comando de control para la gestión de identidad de datos:

*   **/vault**: Muestra la bóveda activa y el espacio ocupado.
*   **/vault list**: Lista todas las bóvedas del usuario con sus IDs.
*   **/vault use `<vault_id>`**: Cambia la base de datos activa para la sesión actual.
*   **/vault new `<name>`**: Crea una nueva bóveda vacía.

## 7. Impacto en el Singleton DB-Writer

El `db-writer` debe ser ahora **Path-Aware** (consciente de la ruta).

*   **Payload de Redis:** El Gateway debe incluir la ruta absoluta del archivo resuelto en el mensaje de la cola.
    *   `{"task_id": "...", "db_path": "/abs/path/to/vault.duckdb", "query": "..."}`
*   **Lógica del Writer:** El proceso C++ abre la conexión al `db_path` específico, ejecuta la tarea y cierra (o mantiene un pool de conexiones recientes para optimizar).

## 8. Garantías de Habeas Data y Seguridad

1.  **Aislamiento Físico:** Un usuario nunca puede ejecutar un `ATTACH` fuera de `db/private/{user_id}/`, `db/shared/{user_id}/` o `db/shared/{tenant_id}/` coherente con el tenant de la petición. El Gateway y el DB Writer validan la ruta antes de encolar/ejecutar.
2.  **Destrucción Granular:** El usuario puede solicitar borrar una bóveda específica (`/vault rm <id>`). El sistema elimina el archivo físico y los registros en `user_vaults`, cumpliendo con el derecho de supresión sin afectar las otras bóvedas del usuario.
3.  **Portabilidad:** El comando `duckops export --vault <id>` empaqueta el archivo `.duckdb` y lo entrega al usuario, garantizando la soberanía total sobre su información.
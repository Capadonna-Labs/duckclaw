# Pipeline Singleton Writer Bridge

Especificación del flujo **API Gateway → Redis → DB Writer → DuckDB** y de cómo validarlo mediante tests automatizados.

**Relación con otras specs:** El Singleton Writer Bridge se describe en [00_System_Infrastructure.md](00_System_Infrastructure.md) (resiliencia) y en [01_Analytical_Memory_Architecture.md](01_Analytical_Memory_Architecture.md) (motores de persistencia). Este documento detalla el **pipeline de prueba** y cómo validarlo con el test unitario correspondiente.

---

## 1. Objetivo

- Probar de forma reproducible que las escrituras a DuckDB pasan por la cola Redis y son aplicadas por un único proceso (DB Writer), evitando locks y condiciones de carrera.
- Ofrecer una forma estandarizada (test unitario/pytest) de verificar el pipeline completo sin depender de un script manual.

---

## 2. Flujo detallado

### 2.1 Componentes

| Componente       | Ubicación               | Función |
|------------------|-------------------------|--------|
| **Redis**        | `localhost:6379` (o `REDIS_URL`) | Cola `duckdb_write_queue`: lista por la que el Gateway empuja mensajes y el DB Writer hace pop bloqueante. |
| **API Gateway**  | `services/api-gateway/` | Acepta `POST /api/v1/db/write` con cuerpo JSON; valida que no sea `SELECT`; genera `task_id`; serializa payload y hace **LPUSH** a la cola. Responde 202 con `{ "status": "enqueued", "task_id": "..." }`. |
| **DB Writer**    | `services/db-writer/`   | Bucle infinito: **BRPOP** bloqueante sobre `duckdb_write_queue`; por cada mensaje, parsea JSON (`task_id`, `query`, `params`), ejecuta `conn.execute(query, params)` sobre DuckDB (en hilo con `asyncio.to_thread`), registra éxito/error en logs. Una sola conexión DuckDB en modo lectura-escritura. |
| **DuckDB**       | `db/duckclaw.duckdb` (por defecto, respecto a la raíz del repo) | Base única escrita exclusivamente por el DB Writer; los agentes y lectores pueden abrirla en solo lectura. |

### 2.2 Secuencia (paso a paso)

1. **Cliente** envía `POST /api/v1/db/write` con body:
   ```json
   {
     "query": "INSERT INTO tabla (a, b) VALUES (?, ?)",
     "params": [1, "texto"],
     "tenant_id": "default"
   }
   ```
2. **API Gateway** comprueba que `query` no empiece por `SELECT`; asigna `task_id` (UUID); arma payload `{ "task_id", "tenant_id", "query", "params" }` y hace `LPUSH duckdb_write_queue JSON.stringify(payload)`.
3. **Redis** mantiene la cola; el mensaje queda al principio de la lista.
4. **DB Writer** (que está bloqueado en `BRPOP duckdb_write_queue`) recibe el mensaje; deserializa el JSON; ejecuta `conn.execute(query, params)` en DuckDB; escribe en log `[task_id] Escritura exitosa`.
5. El **cliente** ya ha recibido 202 con `task_id` sin esperar a que DuckDB termine; la consistencia es eventual (la escritura se aplica segundos después).

### 2.3 Formato del mensaje en Redis

Cada elemento de la lista `duckdb_write_queue` es un JSON con:

- `task_id` (string, UUID)
- `tenant_id` (string, p. ej. `"default"`)
- `query` (string): una sola sentencia SQL parametrizada (placeholders `?`).
- `params` (lista): valores en orden para los `?`.

El DB Writer ejecuta **una sentencia por mensaje**. Para `CREATE TABLE` y un `INSERT` hacen falta dos peticiones (dos mensajes en cola).

### 2.4 Seguridad y restricciones

- El Gateway rechaza con 400 cualquier `query` cuyo `trim().upper()` empiece por `SELECT` (las lecturas no deben ir a la cola de escritura).
- El DB Writer usa parámetros preparados (`params`), reduciendo riesgo de inyección SQL.
- En producción, el Gateway debe estar protegido por auth (p. ej. `X-Tailscale-Auth-Key` o JWT) según [00_System_Infrastructure.md](00_System_Infrastructure.md).

---

## 3. Validación automatizada (pytest)

### 3.1 Ubicación y propósito

- **Test:** `tests/run_singleton_writer_pipeline.py`
- **Propósito:** Validar con pytest que:
  - El contrato del endpoint `POST /api/v1/db/write` es estable (payloads válidos, rechazo de `SELECT`, `task_id` presente, etc.).
  - La app FastAPI del Gateway responde correctamente con Redis mockeado.
  - (Opcional) El pipeline completo (Redis real + DB Writer + Gateway) funciona end‑to‑end.

### 3.2 Requisitos previos

- **Python 3.9+**
- **[uv](https://github.com/astral-sh/uv)** (recomendado) o `pip`
- Dependencias instaladas desde la **raíz del repo**:
- **Redis** accesible en `localhost:6379` (puede levantarse con Docker, ver abajo).

```bash
uv sync
```

Si se usa **Docker** para Redis (recomendado en desarrollo):

1. Asegúrate de que **Docker Desktop** esté instalado y en ejecución (en Windows/macOS).
2. Desde la raíz del repo o cualquier directorio:

```bash
docker run -d --name duckclaw-redis -p 6379:6379 redis:7-alpine
```

Esto levanta un contenedor Redis escuchando en `localhost:6379` que satisface `REDIS_URL=redis://localhost:6379/0`.

### 3.3 Tests unitarios (sin Redis real)

Los tests unitarios comprueban:

- Construcción del payload (`query`, `params`, `tenant_id`) y que los payloads de `CREATE TABLE` e `INSERT` usados en el pipeline cumplen el contrato del Gateway.
- Comportamiento de `wait_health` cuando el servidor devuelve 200 (mock de `urllib.request.urlopen`).
- Comportamiento de `ensure_redis` cuando Redis y Docker no están disponibles (mocks).
- Endpoints del Gateway con `fastapi.testclient.TestClient` y Redis mockeado:
  - `GET /health` → 200 + `{ "status": "ok", "service": ... }`
  - `POST /api/v1/db/write` con `SELECT` → 400
  - `POST /api/v1/db/write` con `INSERT` → 202 + `{"status": "enqueued", "task_id": "..." }`
  - `POST /api/v1/db/write` con `CREATE TABLE` → 202

Para ejecutar solo estos tests (sin integración):

```bash
uv run pytest tests/run_singleton_writer_pipeline.py -v -m "not integration"
```

### 3.4 Test de integración (pipeline completo)

El mismo archivo contiene un test marcado como `@pytest.mark.integration` que:

1. Llama a `ensure_redis()` para verificar que hay un Redis accesible (o levantarlo con Docker).
2. Crea el directorio `db/` en la raíz del repo si no existe.
3. Arranca el **DB Writer** (`services/db-writer/main.py`) en segundo plano.
4. Arranca el **API Gateway** (`services/api-gateway/main.py` vía `uvicorn`) en segundo plano.
5. Usa `wait_health(GATEWAY_URL)` hasta que `/health` devuelva 200.
6. Ejecuta `post_write()` para enviar dos POST al Gateway:
   - `CREATE TABLE IF NOT EXISTS _pipeline_test (id INTEGER, msg VARCHAR)`
   - `INSERT INTO _pipeline_test (id, msg) VALUES (?, ?)` con `[1, "Singleton Writer Bridge OK"]`
7. Espera unos segundos y hace shutdown ordenado de ambos procesos.

Este test **no se ejecuta por defecto**. Para lanzarlo explícitamente:

```bash
# PowerShell
$env:RUN_SINGLETON_PIPELINE_INTEGRATION="1"; uv run pytest tests/run_singleton_writer_pipeline.py -v -m integration

# Para ver los logs detallados del pipeline en la salida (prints):
$env:RUN_SINGLETON_PIPELINE_INTEGRATION="1"; uv run pytest tests/run_singleton_writer_pipeline.py -v -m integration --capture=no
```

o en shells POSIX:

```bash
RUN_SINGLETON_PIPELINE_INTEGRATION=1 uv run pytest tests/run_singleton_writer_pipeline.py -v -m integration
RUN_SINGLETON_PIPELINE_INTEGRATION=1 uv run pytest tests/run_singleton_writer_pipeline.py -v -m integration --capture=no
```

### 3.5 Verificación manual tras el test de integración

La base por defecto es `db/duckclaw.duckdb` (respecto a la raíz del repo). Tras ejecutar el test de integración, para comprobar que las escrituras se aplicaron:

```bash
uv run python -c "
import duckdb
c = duckdb.connect('db/duckclaw.duckdb', read_only=True)
print(c.execute('SELECT * FROM _pipeline_test').fetchall())
"
```

Se espera al menos una fila: `(1, 'Singleton Writer Bridge OK')`.

---

## 4. Prueba manual (sin tests)

Si se prefiere levantar cada componente en una terminal:

| Paso | Terminal | Comando |
|------|----------|--------|
| 1 | Terminal 1 | `docker run -it --rm -p 6379:6379 redis:7-alpine` |
| 2 | Terminal 2 | `cd services/db-writer && uv run python main.py` |
| 3 | Terminal 3 | `cd services/api-gateway && uv run uvicorn main:app --host 127.0.0.1 --port 8000` |
| 4 | Terminal 4 | Enviar dos POST (una sentencia por petición): |

Crear tabla:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/db/write \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"CREATE TABLE IF NOT EXISTS _test (id INTEGER)\",\"params\":[],\"tenant_id\":\"default\"}"
```

Insertar fila:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/db/write \
  -H "Content-Type: application/json" \
  -d '{"query":"INSERT INTO _test (id) VALUES (?)","params":[1],"tenant_id":"default"}'
```

En los logs del DB Writer (Terminal 2) deben aparecer las dos escrituras correctas.

---

## 5. Configuración y variables de entorno

- **API Gateway** (`services/api-gateway/core/config.py`): `REDIS_URL` (por defecto `redis://localhost:6379/0`). Para desarrollo, `JWT_SECRET` y `N8N_AUTH_KEY` tienen valores por defecto; en producción deben definirse en `.env`.
- **DB Writer** (`services/db-writer/core/config.py`): `REDIS_URL`, `QUEUE_NAME` (por defecto `duckdb_write_queue`), `DUCKDB_PATH` (por defecto `{raíz_repo}/db/duckclaw.duckclaw.duckdb`).
- **Tests de pipeline:** asumen que el Gateway expone `http://127.0.0.1:8000` y que la ruta de la base sigue la convención anterior.

---

## 6. Resumen

- El **Singleton Writer Bridge** centraliza todas las escrituras DuckDB en una cola Redis y un solo proceso (DB Writer), evitando contención.
- El archivo de tests `tests/run_singleton_writer_pipeline.py` proporciona:
  - Tests unitarios rápidos para el contrato del Gateway y helpers del pipeline.
  - Un test de integración opcional para validar el flujo completo **API Gateway → Redis → DB Writer → DuckDB**.

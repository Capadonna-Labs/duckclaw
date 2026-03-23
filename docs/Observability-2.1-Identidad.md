# Observability 2.1 — Refinamiento de identidad en logs

Extiende [Observabilidad 2.0](../specs/features/Observabilidad%202.0%20(Logging%20Estructurado%20y%20M%C3%A9tricas).md) alineando el **worker** mostrado en cada línea con el modelo mental **manager → worker delegado** y comandos **fly** en el gateway.

## Formato de línea

Mismo que 2.0: `YYYY-MM-DD HH:MM:SS | [tenant:worker] | chat_id | mensaje`

En terminal (PM2/stdout), la columna **`chat_id`** usa **color ANSI estable por sesión** (misma paleta que el gateway). Desactivar: `NO_COLOR=1` o `DUCKCLAW_LOG_NO_COLOR=1`.

Los prefijos estructurados siguen siendo: `[REQ]`, `[PLAN]`, `[TOOL]`, `[RES]`, `[SYS]`, `[ERR]`, y **`[FLY]`** para comandos on-the-fly.

## Tabla objetivo (fase → worker en log)

| Fase | Worker en `ctx_worker` | Notas |
|------|------------------------|--------|
| `[REQ]` | `manager` | Entrada HTTP/API; sufijo opcional `(via body)` cuando el mensaje viene del cuerpo JSON. |
| `[PLAN]` | `manager` | Incluye delegación explícita: `-> tasks: [<assigned_worker_id>]`. |
| `[SYS]` en subgrafo del worker | Worker asignado (`finanz`, `TheMindCrupier`, …) | Tras delegación, línea breve `Delegación: manager -> <id>`. |
| `[RES]` | `assigned_worker_id` efectivo | Tras retorno del grafo (`effective_worker_id`). |
| `[FLY]` | `gateway` | Comando normalizado `/nombre` + resumen de respuesta (truncado, sin secretos). |

El campo HTTP **`worker_id`** de la ruta (p. ej. `/api/v1/agent/finanz/chat`) **no** tiene por qué coincidir con el worker de observabilidad en `[REQ]`/`[PLAN]`.

## Implementación (referencia de código)

- `set_log_context` / `structured_log_context`: `packages/shared/src/duckclaw/utils/logger.py`
- Gateway `_invoke_chat`: `services/api-gateway/main.py` — `manager` antes de `log_req`; `log_req(..., source="body")`.
- Manager: `packages/agents/src/duckclaw/graphs/manager_graph.py` — `plan_node` + `log_plan` con `assigned_worker_id`; `invoke_worker_node` + `log_sys` de delegación.
- Worker: `packages/agents/src/duckclaw/workers/factory.py` — logs con etiqueta derivada del template (`worker_id`); `set_log_context` en `prepare` / `agent` / `tools`.
- Fly: `packages/agents/src/duckclaw/graphs/on_the_fly_commands.py` — `structured_log_context(..., worker_id="gateway")` + `log_fly` (`duckclaw.fly`).

## Logger `duckclaw.fly`

Registrado en `DEFAULT_STRUCTURED_LOGGERS` para formatter/filter 2.0 coherente con el resto de servicios DuckClaw.

## LangSmith (trazas / grado producción)

Runs nombrados con **`get_tracing_config`** en `packages/shared/src/duckclaw/utils/langsmith_trace.py`:

- **`run_name`** (columna **Name** en LangSmith): el **worker/template** — p. ej. `Manager` (orquestador), `TheMindCrupier`, `finanz`. El tenant no va en el nombre; sí en tags/metadata.
- **Tags** (sin PII): `tenant:…`, `worker:…`, `env:…`.
- **Metadata**: `tenant_id`, `chat_id`, `worker_template`, `model_version`, `deployment_id`.

Al delegar manager → worker se pasa el **`RunnableConfig` del padre** como `base` para fusionar tags/metadata y conservar el enlace padre-hijo en LangSmith.

**Runs manuales** (`Client.create_run`, p. ej. Telegram Guard): usar **`create_completed_langsmith_run`** con `start_time` y `end_time`; si no, LangSmith deja el run en estado *running* (spinner).

### Variables de entorno

| Variable | Uso |
|----------|-----|
| `DUCKCLAW_LLM_MODEL` | Versión del modelo en `metadata.model_version` (default `unknown`). |
| `COMMIT_HASH` o `DUCKCLAW_COMMIT` | Identificador de despliegue en `metadata.deployment_id` (default `local`). |
| `DUCKCLAW_ENV` | Tag `env:{valor}` (default `dev`; usar `production` en PM2/prod). |

Runs manuales del gateway (Telegram Guard) están **desactivados por defecto** (evitan ruido en LangSmith). Opt-in: `DUCKCLAW_LANGSMITH_LOG_TELEGRAM_GUARD=true` (nombre **`TelegramGuard`**).

### Columna **Input** en la tabla Runs (LangSmith)

La vista previa de la columna **Input** (junto al nombre del run) la elige LangSmith con una heurística; si ves `tenant_id` (p. ej. `default`) en lugar del mensaje:

1. **En código:** el estado raíz del manager incluye **`input`** y **`incoming`** con el mismo texto del usuario (`input` primero, convención LangChain). Eso alinea la traza con lo que suele mostrar la tabla.
2. **En el proyecto LangSmith:** Runs → **Format** → *Configure input and output previews* → elige la traza (p. ej. **Manager**) y fija la ruta de entrada a **`incoming`** o **`input`** (documentación: [configure input/output preview](https://docs.langchain.com/langsmith/configure-input-output-preview)).

## Riesgos

- **ContextVar**: válido mientras el invoke de LangGraph corre en el mismo hilo; si un worker se moviera a otro hilo, habría que re-aplicar `set_log_context` al inicio de ese hilo.

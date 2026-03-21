# Observabilidad 2.0 (Logging Estructurado y Métricas)

## 1. Objetivo Arquitectónico
Transformar el sistema de logs de DuckClaw de un "volcado de texto plano" a un **Data Journey Estructurado**. El objetivo es proporcionar observabilidad de grado empresarial que permita auditar el flujo de ejecución, medir cuellos de botella (latencia por herramienta), controlar costos (consumo de tokens) y rastrear sesiones concurrentes en un entorno Multi-Tenant, todo esto manteniendo la consola de PM2 limpia y legible.

## 2. El Contrato de Formato (Log Standard)

Todas las salidas de log del API Gateway y los Workers deben adherirse estrictamente a este formato:

`YYYY-MM-DD HH:MM:SS | [tenant_id:worker_id] | {chat_id} | [PREFIJO] Mensaje (Métricas)`

### Prefijos Obligatorios:
*   `[REQ]` : Petición entrante al Gateway.
*   `[PLAN]`: Intención estratégica generada por el Manager.
*   `[TOOL]`: Inicio y fin de ejecución de una Skill/Herramienta.
*   `[RES]` : Respuesta final enviada al usuario.
*   `[SYS]` : Eventos de infraestructura (Arranque, Hot-Swap, Sandbox Init).
*   `[ERR]` : Excepciones y fallos.

**Ejemplo de Salida Esperada en PM2:**
```text
2026-03-21 10:36:15 | [powerseal:manager] | 1726618406 |[REQ] "Cotiza 50 abrazaderas"
2026-03-21 10:36:16 | [powerseal:manager] | 1726618406 | [PLAN] [Generar Cotización] | tasks: [QuoteEngine]
2026-03-21 10:36:16 | [powerseal:finanz]  | 1726618406 | [SYS] Sandbox: ON | DB: db/private/1726618406/powerseal.duckdb
2026-03-21 10:36:18 | [powerseal:finanz]  | 1726618406 | [TOOL] QuoteEngine -> OK (⏱️ 1850ms)
2026-03-21 10:36:19 | [powerseal:manager] | 1726618406 | [RES] "Cotización lista..." (⏱️ Total: 4.1s | 🪙 Tokens: 850 [P:600, C:250])
```

## 3. Especificación de Módulo: `StructuredLogger` (ContextVars)

Para no tener que pasar `tenant_id` y `chat_id` como parámetros a cada función del sistema, utilizaremos `contextvars` (nativo de Python `asyncio`).

*   **Ubicación:** `packages/shared/src/duckclaw/utils/logger.py`
*   **Implementación:**
    ```python
    import logging
    import contextvars
    import time
    from functools import wraps

    # Variables de contexto asíncrono
    ctx_tenant = contextvars.ContextVar('tenant', default='default')
    ctx_worker = contextvars.ContextVar('worker', default='manager')
    ctx_chat = contextvars.ContextVar('chat_id', default='unknown')

    class DuckClawLogFilter(logging.Filter):
        def filter(self, record):
            record.tenant = ctx_tenant.get()
            record.worker = ctx_worker.get()
            record.chat_id = ctx_chat.get()
            return True

    # Configuración del Formatter
    # Formato: %(asctime)s | [%(tenant)s:%(worker)s] | %(chat_id)s | %(message)s
    ```

## 4. Especificación de Métricas (Latencia y Tokens)

### A. Latencia de Herramientas (Decorador `@time_it`)
Crear un decorador que envuelva las funciones de las herramientas (`@tool`) para medir su tiempo exacto de ejecución.

```python
def log_tool_execution(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.info(f"[TOOL] {func.__name__} -> OK (⏱️ {elapsed:.0f}ms)")
            return result
        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.error(f"[TOOL] {func.__name__} -> FAILED: {str(e)} (⏱️ {elapsed:.0f}ms)")
            raise
    return wrapper
```

### B. Extracción de Tokens (LangGraph / LLM)
Al finalizar la invocación del grafo (`_ainvoke`), el Gateway debe extraer el uso de tokens del último `AIMessage`.

*   **Lógica en `graph_server.py`:**
    ```python
    final_message = result["messages"][-1]
    usage = final_message.usage_metadata # Disponible en LangChain para modelos compatibles
    if usage:
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)
        logger.info(f"[RES] Respuesta enviada (🪙 Tokens: {total_tokens}[P:{prompt_tokens}, C:{completion_tokens}])")
    ```

## 5. Limpieza de Verbosidad (El Problema del Sandbox)

*   **Problema Actual:** La función `_sandbox_enabled_for_state` imprime un log cada vez que una herramienta verifica si el sandbox está activo, inundando la consola.
*   **Solución:** 
    1. Eliminar el `logger.info` dentro de la función de validación del sandbox.
    2. Mover el log al **inicio de la sesión del worker** (en `invoke_worker` o al compilar el grafo).
    3. Imprimir una sola línea `[SYS]` que resuma el entorno de ejecución (Ruta DB y Estado Sandbox).

## 6. Roadmap de Implementación

1.  **Fase 1 (Core Logger):** Implementar `logger.py` con `contextvars` y configurar el middleware de FastAPI para inyectar `tenant_id` y `chat_id` al inicio de cada request.
2.  **Fase 2 (Limpieza):** Buscar globalmente en el repo los `print()` y `logger.info()` antiguos y reemplazarlos por el nuevo estándar. Eliminar los logs repetitivos del sandbox.
3.  **Fase 3 (Métricas):** Aplicar el decorador a las skills principales (`run_sql`, `get_ibkr_portfolio`, `notion_task_manager`) y extraer los tokens en el Gateway.

## 7. Implementación en código (referencia)

- **Módulo:** `packages/shared/src/duckclaw/utils/logger.py` — `ContextVar` (`tenant` / `worker` / `chat_id`), `DuckClawLogFilter`, `DuckClawStructuredFormatter`, `configure_structured_logging()`, helpers `log_req` / `log_plan` / `log_res` / `log_sys` / `log_err`, decoradores `log_tool_execution_sync` / `log_tool_execution_async`, y `extract_usage_from_messages()` para tokens LangChain (`usage_metadata` o `response_metadata.token_usage`).
- **Nivel de log:** variable de entorno opcional `DUCKCLAW_LOG_LEVEL` (por defecto `INFO`).
- **Gateway:** `services/api-gateway/main.py` — middleware `_observability_context_middleware` (cabeceras `X-Tenant-Id`, `X-Chat-Id`; `worker_id` desde la ruta `/api/v1/agent/{worker_id}/chat`); refinamiento de contexto y `[REQ]` / `[RES]` en `_invoke_chat`.
- **LangGraph HTTP:** `packages/agents/src/duckclaw/graphs/graph_server.py` — `structured_log_context` en `/invoke` y `/stream`; `_ainvoke` adjunta `usage_tokens` al dict de salida.
- **Manager:** `packages/agents/src/duckclaw/graphs/manager_graph.py` — `[PLAN]` en `plan_node`; una línea `[SYS]` (Sandbox ON/OFF + ruta DB) antes de invocar el worker.
- **Sandbox:** sin log por llamada en `_sandbox_enabled_for_state` (`packages/agents/src/duckclaw/workers/factory.py`).
- **Herramientas con latencia:** `read_sql` e `inspect_schema` en `packages/agents/src/duckclaw/graphs/tools.py`; `get_ibkr_portfolio` en `ibkr_bridge.py`; `read_sql` del worker en `factory.py` (equivalente a `run_sql` de la spec). La skill `notion_task_manager` no existe en el monorepo; se usa **`inspect_schema`** como tercera herramienta instrumentada.
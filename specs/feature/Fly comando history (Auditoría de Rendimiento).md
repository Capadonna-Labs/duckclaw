# Comando `/history` (Auditoría de Rendimiento)

**Estado:** Implementado en `on_the_fly_commands.py`. Tabla `task_audit_log`. Integrado en Gateway y Telegram bot.

## 1. Objetivo Arquitectónico
Exponer el historial de ejecución de tareas del agente de forma legible en Telegram. El comando debe filtrar las tareas por `tenant_id` y `worker_id`, mostrando métricas de rendimiento (duración) y estado final, permitiendo auditar el trabajo realizado por el agente sin entrar al Dashboard.

## 2. Especificación del Comando `/history`

*   **Sintaxis:** `/history [n]` (donde `n` es el número de tareas recientes, default=5).
*   **Lógica Interna:**
    1.  **Consulta:** Consultar la tabla `task_audit_log` en DuckDB.
    2.  **Agregación:** Unir con los datos de `task_metadata` para obtener la duración real.
    3.  **Formateo:** Generar un resumen Markdown.

### Query SQL (DuckDB)
```sql
SELECT 
    task_id, 
    query_prefix, 
    status, 
    duration_ms, 
    created_at 
FROM task_audit_log 
WHERE tenant_id = ? 
ORDER BY created_at DESC 
LIMIT ?;
```

## 3. Especificación de Skill: `HistoryRetriever`

*   **Ubicación:** `duckclaw/forge/skills/history_retriever.py`
*   **Lógica:**
    1.  Recuperar las últimas `n` tareas de la base de datos.
    2.  Calcular el promedio de duración de las tareas exitosas para dar contexto al usuario.
    3.  Formatear la salida:
        *   `✅` para `SUCCESS`.
        *   `❌` para `FAILED`.
        *   `⏱️` para mostrar la duración en segundos.

## 4. Contrato de Respuesta (Telegram Markdown)

```markdown
**Historial de Tareas (Últimas 5):**

1. `COT-2026-001` | ✅ SUCCESS | ⏱️ 1.2s
   *Acción: Generar cotización Power Seal*

2. `DB-WRITE-992` | ✅ SUCCESS | ⏱️ 0.4s
   *Acción: Insertar transacción Finanz*

3. `STRIX-EXEC-441` | ❌ FAILED | ⏱️ 5.0s (Timeout)
   *Acción: Ejecutar script Python en Sandbox*

---
**Promedio de ejecución:** 0.85s
**Tareas fallidas (últimas 24h):** 1
```

## 5. Integración (Implementado)

- **Fly command:** `execute_history()` en `on_the_fly_commands.py`; `handle_command` despacha `/history [n]`.
- **Persistencia:** `append_task_audit()` se llama desde el Gateway (`_invoke_chat`) y el Telegram bot tras cada invocación del grafo.
- **Tabla:** `task_audit_log` (task_id, tenant_id, worker_id, query_prefix, status, duration_ms, created_at).

## 6. Ventajas de Cumplimiento (Habeas Data)
*   **Auditoría de Rendimiento:** Al mostrar la duración (`duration_ms`), estás demostrando eficiencia operativa.
*   **Transparencia:** Si una tarea falló (`❌`), el usuario sabe exactamente cuál fue y puede pedirle al agente que la reintente o escalar a Johanna.
*   **Privacidad:** El comando `/history` solo devuelve metadatos de la tarea (título, duración, estado), **nunca el contenido sensible** (ej. el PDF de la cotización o los datos del cliente).
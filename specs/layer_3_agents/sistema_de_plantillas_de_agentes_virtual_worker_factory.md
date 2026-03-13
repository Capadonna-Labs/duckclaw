# Sistema de Plantillas de Agentes (Virtual Worker Factory)

## 1. Objetivo Arquitectónico
Implementar un patrón de diseño *Factory* para instanciar "Trabajadores Virtuales" (Agentes) preconfigurados. El sistema debe permitir un despliegue *Plug & Play* mediante PM2, garantizando el aislamiento de estado (DuckDB) y la asignación estricta de habilidades (Skills) según el rol, cumpliendo con los principios de Soberanía de Datos y trazabilidad forense.

## 2. Estructura del Contrato de Plantilla (Worker Spec)
Cada trabajador virtual se define como un paquete atómico y declarativo dentro del directorio `templates/workers/`.

### Estructura de Directorios:
```text
templates/workers/
└── finanz/
    ├── manifest.yaml       # Configuración core (LLM, temperatura, dependencias)
    ├── system_prompt.md    # Instrucciones del rol (Estilo Anthropic)
    ├── schema.sql          # DDL para inicializar las tablas en DuckDB
    └── skills/             # Herramientas atómicas específicas del rol
        ├── categorize_tx.py
        └── generate_report.py
```

## 3. Especificación de Módulos Core

### Módulo: `WorkerFactory`
*   **Entrada:** `worker_id` (ej. `finanz`), `telegram_chat_id`.
*   **Lógica:**
    1.  Leer `manifest.yaml` y validar dependencias del modelo local (ej. requerimiento de `Llama-3.2-3B-Instruct`).
    2.  Conectar a `DuckDB` y ejecutar `schema.sql` bajo un esquema aislado (ej. `CREATE SCHEMA IF NOT EXISTS finance_worker;`).
    3.  Cargar el `system_prompt.md` en el nodo `Planner` de LangGraph.
    4.  Inyectar dinámicamente las herramientas del directorio `skills/` en el nodo `Executor`.
*   **Salida:** Instancia de LangGraph compilada, con estado persistente, lista para recibir eventos.

### Módulo: `WorkerCLI` (Orquestación Plug & Play)
*   **Comando:** `duckclaw hire <worker_id> --name <instance_name>`
*   **Lógica:**
    1.  Invoca al `WorkerFactory` para validar la plantilla.
    2.  Genera un archivo de entorno específico `.env.<instance_name>`.
    3.  Inyecta la configuración dinámicamente en `ecosystem.config.cjs` usando el `EnvironmentNormalizer`.
    4.  Ejecuta `pm2 start ecosystem.config.cjs --only <instance_name>` para levantar el proceso en *background*.

## 4. Catálogo Inicial de Trabajadores (Roster)

### Plantilla A: `FinanzWorker` (Gestor de Finanzas Personales)
*   **Topología LangGraph:** Ciclo estricto `Planner -> Executor -> SQLValidator -> Explainer`.
*   **Skills Asignadas:** `insert_transaction`, `get_monthly_summary`, `categorize_expense`.
*   **Seguridad de Datos:** Acceso de escritura limitado exclusivamente a las tablas `transactions` y `categories`. Bloqueo total a tablas de sistema mediante el `SQLValidator` (AST Allow-list).
*   **Prompt Core:** "Eres un auditor financiero estricto. Nunca asumas una categoría si la descripción es ambigua; debes preguntar al usuario antes de registrar el dato."

### Plantilla B: `SupportWorker` (Atención al Cliente / RAG)
*   **Topología LangGraph:** Ciclo `Interpreter -> RAG_Retriever -> Validator -> Explainer`.
*   **Skills Asignadas:** `search_knowledge_base`, `get_ticket_status`.
*   **Seguridad de Datos:** Acceso de **Solo Lectura** (Read-Only) a la base de datos vectorial y relacional. Imposibilidad arquitectónica de ejecutar `INSERT` o `UPDATE`.
*   **Prompt Core:** "Eres un agente de soporte empático. Basa tus respuestas ÚNICAMENTE en la evidencia cruda (`raw_evidence`) recuperada. Si la respuesta no está en el contexto, indica que escalarás la consulta."

## 5. Protocolo de Aislamiento y Habeas Data
*   **Aislamiento de Memoria:** Cada instancia de trabajador mantiene su propio `thread_id` en la memoria de LangGraph (Checkpointer). Un `SupportWorker` no tiene acceso al espacio de memoria ni al historial de chat de un `FinanzWorker`.
*   **Auditoría Forense:** En LangSmith, cada traza debe etiquetarse automáticamente con los metadatos `worker_role: <worker_id>` y `instance: <instance_name>`. Esto es crítico para aislar los datasets durante el re-entrenamiento (GRPO) específico por rol.
*   **Sandboxing:** Si una plantilla requiere ejecutar código Python dinámico (ej. un `DataAnalystWorker` generando gráficos de tendencias), sus skills deben enrutarse obligatoriamente a través del `SandboxPipeline` (Zero Trust Execution).

---

## 6. Implementación

| Componente | Ubicación |
|------------|-----------|
| **WorkerFactory** | `duckclaw/workers/factory.py` |
| **Manifest / Loader** | `duckclaw/workers/manifest.py`, `duckclaw/workers/loader.py` |
| **WorkerCLI (hire)** | `duckops hire <worker_id> [--name <instance_name>]` en `duckclaw/ops/cli.py` y `manager.hire()` |
| **Run worker (PM2)** | `duckclaw/workers/run_worker.py` (HTTP POST /invoke) |
| **Plantilla FinanzWorker** | `templates/workers/finanz/` |
| **Plantilla SupportWorker** | `templates/workers/support/` |

### Comandos

```bash
duckops hire --list                    # Listar plantillas disponibles
duckops hire finanz --name FinanzBot   # Desplegar worker vía PM2
pm2 logs FinanzBot                     # Logs del worker
curl -X POST http://localhost:8124/invoke -d '{"message":"Resumen del mes"}'  # Invocar (puerto por instancia)
```

### Metadatos LangSmith

En despliegue con `hire` se genera `.env.<instance_name>` con `LANGCHAIN_TAGS=worker_role:<worker_id>,instance:<instance_name>` para trazabilidad forense.
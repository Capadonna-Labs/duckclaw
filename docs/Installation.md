# Instalación y Despliegue Automatizado (DuckOps Wizard)

## 1. Objetivo Arquitectónico
Estandarizar el proceso de aprovisionamiento y despliegue de la plataforma DuckClaw en cualquier entorno (Mac Mini, VPS Linux, Windows) mediante una interfaz de línea de comandos (CLI) interactiva y segura. El `DuckOps Wizard` elimina la dependencia de scripts Bash frágiles, garantizando que la configuración de variables de entorno, la creación de bases de datos y el registro de microservicios (PM2/Systemd) se realicen bajo principios de **Zero-Trust** y **Soberanía de Datos**.

## 2. Prerrequisitos de Infraestructura (Pre-flight)
Antes de invocar el Wizard, el entorno host debe contar con:
1.  **Gestor de Paquetes:** `uv` (para resolución ultrarrápida de dependencias Python).
2.  **Broker de Mensajes:** `Redis` corriendo en el puerto 6379 (vía Docker, OrbStack o nativo).
3.  **Gestor de Procesos (Opcional pero recomendado):** `pm2` (Node.js) o `systemd` (Linux) para persistencia de servicios.

## 3. Flujo de Ejecución del Wizard (`duckops init`)

El comando de entrada es `uv run duckops init`. El flujo interactivo se divide en 4 fases críticas:

### Fase 0: Detección de Estado (State Awareness)
*   **Lógica:** El Wizard escanea el sistema operativo buscando gestores de procesos (`pm2 jlist` o `systemctl`).
*   **Acción:** Si detecta servicios de DuckClaw previamente instalados (ej. `DuckClaw-Gateway`, `DuckClaw-DB-Writer`), interrumpe el flujo de instalación desde cero y ofrece un menú de **Gestión de Servicios** para reiniciar, detener o reconfigurar los procesos existentes en caliente.

### Fase 1: Configuración del Cerebro (Core Config)
Si es una instalación limpia, el Wizard solicita los parámetros fundamentales:
1.  **Modo del Bot:** `echo` (pruebas) o `langgraph` (producción con memoria bicameral).
2.  **Ruta de Base de Datos:** Solicita el nombre del archivo.
    *   *Seguridad (Habeas Data):* El Wizard normaliza automáticamente cualquier input a la carpeta segura `db/` (ej. `powerseal` -> `db/powerseal.duckdb`). Si el archivo no existe, lo crea e inicializa el esquema.
3.  **Proveedor LLM:** Menú interactivo para seleccionar el motor de inferencia (`mlx` para Mac M4, `deepseek`, `openai`, `iotcorelabs`, etc.).

### Fase 2: Observabilidad y Telemetría
*   **Trazas GRPO:** Pregunta si se deben guardar las trazas locales en `train/grpo_olist_traces.jsonl` para el futuro pipeline SFT.
*   **LangSmith:** Configura la exportación de telemetría (requiere `LANGCHAIN_API_KEY`).

### Fase 3: Generación de Artefactos y Despliegue (The Forge)
Una vez confirmados los datos, el Wizard "forja" el entorno:
1.  **Sincronización de Entorno (`.env`):** Escribe las variables de forma segura.
    *   *Smart Mapping:* Escribe `DUCKCLAW_DB_PATH` para el grafo y el Gateway y automáticamente inyecta `DUCKDB_PATH` para que el microservicio `db-writer` apunte al mismo archivo sin intervención manual.
2.  **Generación de Configuración PM2/Systemd:** Crea los archivos `ecosystem.*.config.cjs` o las unidades `.service` inyectando las rutas absolutas del entorno virtual (`.venv/bin/python3`) para evitar fallos de `PATH`.
3.  **Arranque:** Levanta los microservicios en el orden correcto.

## 4. Topología de Servicios Desplegados

Al finalizar el Wizard, el sistema queda orquestado con los siguientes procesos (visibles vía `pm2 list`):

| Servicio PM2 | Rol Arquitectónico | Comando Subyacente |
| :--- | :--- | :--- |
| **`DuckClaw-Gateway`** | API Unificada (FastAPI). Recibe tráfico de n8n/Angular, encola escrituras y sirve SSE. | `uvicorn main:app --app-dir services/api-gateway` |
| **`DuckClaw-DB-Writer`** | Consumidor Singleton. Lee de Redis y escribe en DuckDB garantizando ACID. | `python services/db-writer/main.py` |
| **`DuckClaw-MLX_Inference`**| (Solo Mac) Servidor MLX local compatible con OpenAI API. | `bash mlx/start_mlx.sh` |

## 5. Protocolo de Seguridad (Manejo de Secretos)
*   **Censura en Pantalla:** Durante el resumen de configuración, los tokens (ej. Telegram) se muestran censurados (`8266...R5ws`) para evitar fugas si se comparte pantalla o se toman capturas.
*   **Volatilidad:** El token de Telegram se solicita en tiempo de ejecución si no existe en el `.env`, pero **no se guarda en el JSON de preferencias** (`wizard_config.json`), forzando a que resida únicamente en el `.env` protegido por permisos del OS.

## 6. Guía Rápida de Operación (Cheat Sheet)

Estos son los comandos del día a día:

```bash
# 1. Instalación desde cero o reconfiguración interactiva
uv run duckops init

# 2. Levantar el API Gateway manualmente (Modo Dev)
uv run duckops serve --gateway

# 3. Ver el estado de los servicios en background
pm2 status

# 4. Ver logs en tiempo real del DB-Writer (para auditar escrituras)
pm2 logs DuckClaw-DB-Writer
```
# DuckClaw 🦆⚔️

High-performance C++ analytical memory layer for sovereign AI agents. 

## Overview
DuckClaw is a native bridge between **DuckDB** and **Python**, optimized for **Apple Silicon (M4)**. It provides AI agents with a structured, high-speed analytical memory, allowing them to execute complex SQL queries and manage state with sub-millisecond latency.

Built by **IoTCoreLabs** for the Sovereign Agentic Ecosystem.

## Core Features
- **Native Performance**: Written in C++17 for minimal overhead.
- **Sovereign by Design**: Operates entirely on local `.duckdb` files, ensuring 100% data privacy.
- **Agent-Friendly**: Returns query results as **JSON** by default, ideal for LLM context injection and GRPO training loops.
- **Optimized for M4**: Leverages Apple Silicon's unified memory architecture for zero-copy data transfers.

## Installation

### Prerequisites
- macOS (Apple Silicon M1/M2/M3/M4)
- CMake >= 3.18
- DuckDB (`brew install duckdb`)
- Pybind11 (`pip install pybind11`)

### Build from source

Con **pip** (evita el error “No module named pip” en entornos aislados usando `--no-build-isolation`):

```bash
git clone https://github.com/Arevalojj2020/duckclaw.git
cd duckclaw
pip install cmake pybind11   # dependencias de build en tu venv
pip install -e . --no-build-isolation
# Con extra Telegram:
pip install -e ".[telegram]" --no-build-isolation
```

Con **uv** (recomendado):

```bash
uv pip install -e .
```

**Nota:** La primera compilación puede tardar **~5–7 minutos** porque se descarga y compila DuckDB. Para intentar usar DuckDB de Homebrew: `CMAKE_ARGS="-DDUCKDB_ROOT=/opt/homebrew/opt/duckdb" pip install -e . --no-build-isolation` (Intel: `/usr/local/opt/duckdb`).

### Quick Start (Python)

```python
import duckclaw

# Initialize Sovereign Memory
db = duckclaw.DuckClaw("vfs/agent_memory.duckdb")

# Execute DDL
db.execute("CREATE TABLE IF NOT EXISTS telemetry (x DOUBLE, y DOUBLE, z DOUBLE, event TEXT)")

# Insert Data
db.execute("INSERT INTO telemetry VALUES (100.5, 64.0, -200.1, 'Zombie Attack')")

# Query Data (returns JSON string by default)
results = db.query("SELECT * FROM telemetry")
print(results)
# Output: [{"x":"100.5","y":"64.0","z":"-200.1","event":"Zombie Attack"}]
```

## Security Testing (Strix)

Use Strix for manual security assessments against this repository.

### Prerequisites
- Docker running locally
- Strix CLI installed
- `STRIX_LLM` configured (example: `openai/gpt-5`)
- `LLM_API_KEY` configured

### Base command
```bash
strix -n --target ./
```

### Standardized manual runs
```bash
# Quick triage
./scripts/pentest_strix.sh quick

# Deeper manual assessment
./scripts/pentest_strix.sh deep
```

### Artifacts and review criteria
- CLI logs are written to `.security/pentest-logs/`
- Strix run artifacts are written to `strix_runs/`
- Prioritize remediation for `critical` and `high` findings first
- Re-run the same mode after fixes to validate closure

## Third-Party Integration: Telegram (Polling)

DuckClaw includes a reusable Telegram base class at `duckclaw/integrations/telegram.py` that automatically persists incoming updates/messages into DuckDB.

### Prerequisites
- Telegram bot token from BotFather
- Optional dependency: `python-telegram-bot`
- DuckClaw installed in editable mode

```bash
pip install -e ".[telegram]" --no-build-isolation
```

### Quick start (local polling)
1. Create and export your token:
   ```bash
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   export DUCKCLAW_DB_PATH="telegram.duckdb"
   ```
2. Run the runnable example:
   ```bash
   python examples/telegram_bot.py
   ```
   Or run the one-line interactive wizard (asks token input if missing):
   ```bash
   ./scripts/install_duckclaw.sh
   ```
   The wizard uses `rich` and starts with two modes:
   - `quick`: minimal prompts and default values
   - `manual`: full step-by-step setup

   It guides you with:
   - dependency checks
   - token input (secure prompt)
   - DB path selection
   - launch confirmation
3. Send a message to your bot from Telegram.
4. Validate persistence in DuckClaw:
   ```python
   import duckclaw
   db = duckclaw.DuckClaw("telegram.duckdb")
   print(db.query("SELECT chat_id, username, text, received_at FROM telegram_messages ORDER BY received_at DESC LIMIT 10"))
   ```

### What is persisted automatically
Each incoming update stores:
- `message_id`, `chat_id`, `user_id`, `username`
- message `text`
- full `raw_update_json`
- `received_at` timestamp

For complete setup and troubleshooting, see `docs/telegram-integration.md`.

## Bot inteligente (LangGraph y proveedores)

El wizard y el ejemplo de Telegram permiten elegir un **modo del bot** (echo o langgraph) y, en modo langgraph, un **proveedor** para respuestas inteligentes:

| Proveedor     | Descripción                    | Variables de entorno / configuración                    |
|---------------|--------------------------------|---------------------------------------------------------|
| **none_llm**  | Sin LLM (reglas + memoria DuckClaw) | Ninguna. Usa solo contexto guardado en DuckClaw.        |
| **openai**    | OpenAI API                     | `OPENAI_API_KEY` (obligatorio)                          |
| **anthropic** | Anthropic API                  | `ANTHROPIC_API_KEY` (obligatorio)                       |
| **ollama**    | Ollama local                   | URL en wizard (ej. `http://localhost:11434`) + modelo   |
| **iotcorelabs** | IoTCoreLabs | URL en wizard; opcional `IOTCORELABS_API_KEY`          |
| **mlx**       | MLX (servidor local OpenAI-compatible) | URL base y nombre del modelo en wizard; opcional `MLX_LLM_API_KEY`   |

Si faltan credenciales o URL requeridos, el wizard y el bot hacen **fail-fast** con un mensaje claro.

### Herramientas DuckClaw en el agente (modo langgraph)

En modo **langgraph** con cualquier proveedor LLM (openai, anthropic, ollama, mlx, etc.), el agente tiene herramientas para consultar y modificar la base DuckDB según los mensajes de Telegram:

| Herramienta       | Descripción |
|-------------------|-------------|
| `list_tables`     | Lista las tablas de la base de datos. |
| `describe_table`  | Describe las columnas de una tabla (argumento: `table_name`, solo letras, números y `_`). |
| `run_read_sql`    | Ejecuta consultas de solo lectura: `SELECT`, `WITH`, `SHOW`, `DESCRIBE`. Devuelve JSON. |
| `run_write_sql`   | Ejecuta escrituras permitidas: `INSERT`, `UPDATE`, `DELETE`. |

**Política safe_write:** no se permiten `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `ATTACH`, `COPY`, etc. Solo lectura con `run_read_sql` y escritura limitada a `INSERT`/`UPDATE`/`DELETE` con `run_write_sql`. Si el usuario pide una operación no permitida, el agente debe responder que no está disponible.

**Ejemplos de uso desde Telegram:**
- *"¿Qué tablas hay?"* → el agente usa `list_tables` y responde con la lista.
- *"Describe telegram_messages"* → `describe_table("telegram_messages")`.
- *"Dame los últimos 5 mensajes"* → `run_read_sql("SELECT text FROM telegram_messages ORDER BY received_at DESC LIMIT 5")`.
- *"Inserta un registro en la tabla X"* → el agente puede usar `run_write_sql` con un `INSERT` válido (si la tabla existe y el usuario lo pide explícitamente).

### Instalación por proveedor

- Solo Telegram (echo o langgraph con `none_llm`). LangGraph viene incluido en el paquete:
  ```bash
  pip install -e ".[telegram]" --no-build-isolation
  ```
- Con todos los proveedores (OpenAI, Anthropic, Ollama, etc.):
  ```bash
  pip install -e ".[all]" --no-build-isolation
  ```
- Solo un proveedor: instala el paquete correspondiente además de `.[telegram]` (ej. `pip install langchain-openai` para OpenAI).

### Ejecución

1. Ejecuta el wizard y elige modo **langgraph** y el proveedor deseado:
   ```bash
   ./scripts/install_duckclaw.sh
   ```
2. Para OpenAI o Anthropic, exporta la API key antes de arrancar (o cuando el wizard lo pida no habrá token en env y fallará la validación):
   ```bash
   export OPENAI_API_KEY="sk-..."
   ./scripts/install_duckclaw.sh
   ```
3. El bot muestra en logs el proveedor y modelo activos al iniciar.

## License

MIT License. See LICENSE for more information.
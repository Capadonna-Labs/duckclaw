# DuckClaw 🦆⚔️

**High-performance C++ analytical memory layer for sovereign AI agents.**

Built by [IoTCoreLabs](https://iotcorelabs.io) · Optimized for Apple Silicon · Powered by DuckDB

---

## What is DuckClaw?

DuckClaw is a native C++17 bridge between **DuckDB** and Python AI agents. It gives agents a structured, high-speed analytical memory: SQL queries, state management, and full data sovereignty — all local, all fast.

- **Zero cloud dependency** — operates entirely on local `.duckdb` files
- **Sub-millisecond latency** — C++ core with zero-copy data transfers on Apple Silicon
- **Agent-ready** — query results return as JSON, ideal for LLM context injection
- **LangGraph native** — bicameral memory architecture with OLAP + semantic graph layers

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   DuckClaw Stack                    │
├─────────────────────────────────────────────────────┤
│  Telegram Bot  │  LangGraph API  │  LangSmith       │
│  (pm2)         │  (duckops serve)│  (tracing)       │
├─────────────────────────────────────────────────────┤
│           LangGraph Agent (general_graph)           │
│   run_sql │ inspect_schema │ manage_memory          │
├─────────────────────────────────────────────────────┤
│         Bicameral Memory (BicameralOrchestrator)    │
│    OLAP Layer (DuckDB)  │  Semantic Graph Layer     │
├─────────────────────────────────────────────────────┤
│              DuckClaw C++ Core (_duckclaw.so)        │
│                   DuckDB Engine                     │
└─────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- macOS (Apple Silicon M1/M2/M3/M4)
- Python ≥ 3.9
- CMake ≥ 3.18
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Install

```bash
git clone https://github.com/Arevalojj2020/duckclaw.git
cd duckclaw

# Recommended
uv sync --extra agents

# Or with pip
pip install cmake pybind11
pip install -e ".[agents]" --no-build-isolation
```

> First build downloads and compiles DuckDB (~5–7 min). Subsequent installs are instant.

### Python usage

```python
import duckclaw

db = duckclaw.DuckClaw("memory.duckdb")

db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER, label TEXT)")
db.execute("INSERT INTO events VALUES (1, 'startup')")

results = db.query("SELECT * FROM events")
print(results)
# [{"id": "1", "label": "startup"}]
```

---

## Telegram Bot

DuckClaw ships with an intelligent Telegram bot powered by LangGraph and bicameral memory.

### Setup wizard

```bash
./scripts/install_duckclaw.sh
```

The wizard detects existing PM2 services, guides you through LLM provider selection, and generates the PM2 ecosystem config.

### Manual start

```bash
# Set env vars
export TELEGRAM_BOT_TOKEN="your_token"
export DUCKCLAW_DB_PATH="db/gateway.duckdb"   # optional; default is db/gateway.duckdb
export DUCKCLAW_LLM_PROVIDER="mlx"           # openai | anthropic | deepseek | huggingface | mlx | ollama | none_llm
export DUCKCLAW_LLM_BASE_URL="http://127.0.0.1:8080/v1"

# Run
python -m duckclaw.agents.telegram_bot
```

### Bot commands

| Command | Description |
|---------|-------------|
| `/setup` | Change framework and system_prompt on the fly |
| **On-the-Fly CLI** (reconfig without restart) | |
| `/role <worker_id>` | Switch agent role to a Virtual Worker template (e.g. `finanz`, `support`). Uses Worker Factory. |
| `/skills` | List the tools (skills) currently enabled for the agent. |
| `/forget` | Clear conversation history for this chat and reset graph state (Habeas Data). |
| `/context on` \| `/context off` | Enable or disable long-term context (number of messages in history). |
| `/prompt` \| `/prompt <texto>` | Show current system prompt, or set a new one (replaces the SYSTEM instruction). |
| `/audit` | Show last execution evidence: latency, SQL (if any), LangSmith run_id. |
| `/health` | Check DuckDB and inference endpoint (MLX) status and latency. |
| `/approve` \| `/reject` | Human-in-the-loop: approve or reject a pending operation (when graph is in interrupt state). |
| Any other message | Processed by LangGraph agent (or by the active worker if `/role` was set). |

### Supported LLM providers

| Provider | Env var | Notes |
|----------|---------|-------|
| `openai` | `OPENAI_API_KEY` | GPT-4o, GPT-4, etc. |
| `anthropic` | `ANTHROPIC_API_KEY` | Claude 3.5, etc. |
| `deepseek` | `DEEPSEEK_API_KEY` | DeepSeek-Chat |
| `huggingface` | `HUGGINGFACE_API_KEY` or `HF_TOKEN` | Serverless Inference API or Dedicated Endpoints |
| `mlx` | `MLX_MODEL_PATH` / `MLX_MODEL_ID` | Local Apple Silicon inference |
| `ollama` | — | Local Ollama server |
| `iotcorelabs` | `IOTCORELABS_API_KEY` (optional) | IoTCoreLabs endpoint |
| `none_llm` | — | Rules + DuckClaw memory only |

---

## LangGraph Agent Tools

In `langgraph` mode the agent has direct access to DuckDB:

| Tool | Description |
|------|-------------|
| `run_sql` | Execute SQL — SELECT, INSERT, UPDATE, CREATE TABLE, etc. |
| `inspect_schema` | List all tables and their columns |
| `manage_memory` | Get/set/delete user preferences (`action`, `key`, `value`) |

**Write policy:** `DROP`, `TRUNCATE`, `ATTACH`, `DETACH`, `COPY`, `EXPORT` are blocked. `CREATE TABLE`, `INSERT`, `UPDATE`, `DELETE` are allowed.

---

## Persistence with PM2

DuckClaw uses PM2 to keep the bot and inference server alive across reboots.

### Start services

```bash
pm2 start ecosystem.core.config.cjs   # Telegram bot (DuckClaw-Brain)
pm2 start ecosystem.config.cjs        # MLX inference server (DuckClaw-Inference)
pm2 save && pm2 startup
```

### Monitor

```bash
duckops status                         # Rich table summary
pm2 logs DuckClaw-Brain                # Live logs
pm2 restart DuckClaw-Brain --update-env
```

### ecosystem.core.config.cjs (generated by wizard)

The wizard generates this file automatically. Edit it to change the bot name, DB path, LLM provider, or any env variable, then run `pm2 restart DuckClaw-Brain --update-env`.

---

## LangGraph API Server (LangSmith Studio)

Expose the LangGraph agent as a REST API for external tools, LangSmith Studio, or internet access.

### Start server

```bash
# Direct (blocks terminal)
duckops serve --port 8123

# As persistent PM2 service
duckops serve --pm2 --name DuckClaw-API --port 8123
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Server info, active model, tracing status |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Swagger UI |
| `POST` | `/invoke` | Invoke graph: `{"message": "...", "chat_id": "...", "history": [...]}` |
| `POST` | `/stream` | Streaming SSE response |
| `GET` | `/graph` | Graph structure (nodes/edges) |

### Connect to LangSmith Studio

```bash
# Starts server + Cloudflare tunnel (works from Safari and over internet)
.venv/bin/langgraph dev --tunnel
```

Then open [smith.langchain.com/studio](https://smith.langchain.com/studio) and connect to the tunnel URL.

> **Note:** Use Chrome/Firefox for `localhost`. For Safari or internet access, always use `--tunnel`.

---

## Tailscale Mesh (Red Distribuida)

DuckClaw soporta una arquitectura de red privada entre Mac Mini (agentes + MLX) y VPS (n8n, PostgreSQL) usando **Tailscale** (WireGuard). El tráfico permanece cifrado E2EE dentro del túnel, cumpliendo Habeas Data.

### Instalación

**Mac Mini / local:**
```bash
./scripts/tailscale_setup.sh
```

**VPS (vía SSH):**
```bash
ssh user@vps 'bash -s' < scripts/tailscale_install_vps.sh
```

### Configuración

1. **ACLs** en [Tailscale Admin Console](https://login.tailscale.com/admin/acls): define `tag:vps` y `tag:mac-mini` para Privilegio Mínimo.
2. **Autenticación API:** añade a `.env`:
   ```env
   DUCKCLAW_TAILSCALE_AUTH_KEY=tu_clave_secreta
   ```
   Las peticiones a `/invoke`, `/stream`, etc. deben incluir `X-Tailscale-Auth-Key: tu_clave_secreta`. `/` y `/health` no requieren auth.
3. **Puerto:** para usar 8000 (según spec): `DUCKCLAW_API_PORT=8000 duckops serve --port 8000`

### Skill tailscale_status

Habilita el tool en el grafo general añadiendo `tailscale_status` a `tools` en el YAML, o en workers con `skills: [{ tailscale: { tailscale_enabled: true } }]`. El tool verifica `ConnectionStatus: Active|Down` y lista peers.

### Verificación

Desde el VPS hacia la Mac Mini:
```bash
curl http://<MAC_TAILSCALE_IP>:8123/health
```

---

## LangSmith Tracing

Add these to your `.env` to send all LangGraph runs to LangSmith:

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=MyProject
```

Traces include: LLM calls, tool invocations, graph node steps, latency, and token usage.

---

## Environment Variables

All variables go in `.env` at the project root. They are loaded automatically by the bot, wizard, and API server.

```env
# Telegram
TELEGRAM_BOT_TOKEN=...

# Database (one .duckdb for Gateway: conversations + agent SQL)
DUCKCLAW_DB_PATH=/path/to/db/gateway.duckdb   # optional; default is db/gateway.duckdb

# LLM
DUCKCLAW_LLM_PROVIDER=mlx
DUCKCLAW_LLM_MODEL=
DUCKCLAW_LLM_BASE_URL=http://127.0.0.1:8080/v1

# MLX local inference
MLX_MODEL_PATH=/path/to/models/Slayer-8B-V1.1
MLX_MODEL_ID=/path/to/models/Slayer-8B-V1.1
MLX_PYTHON=/path/to/mlx_env/bin/python
MLX_PORT=8080

# LangSmith
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=Finanz

# Tailscale Mesh (opcional)
DUCKCLAW_TAILSCALE_AUTH_KEY=...   # Valida X-Tailscale-Auth-Key en /invoke, /stream
DUCKCLAW_API_PORT=8123            # Puerto del API (default 8123; usar 8000 para spec Tailscale)
```

> `.env` is git-ignored. Never commit tokens or API keys.

---

## duckops CLI

```bash
duckops status                          # Show all PM2 services
duckops status --name DuckClaw-Brain    # Filter by name
duckops serve --port 8123               # Start LangGraph API server
duckops serve --pm2 --name DuckClaw-API # Deploy API server via PM2
duckops deploy --name ... --command ... # Deploy any command as persistent service
```

---

## MLX Local Inference (Apple Silicon)

Run a local LLM on Apple Silicon using `mlx_lm`:

```bash
# Set model path in .env
MLX_MODEL_PATH=/path/to/models/Slayer-8B-V1.1

# Start via PM2
pm2 start ecosystem.config.cjs

# Or manually
./mlx/start_mlx.sh
```

The MLX server exposes an OpenAI-compatible API at `http://127.0.0.1:8080/v1`. The bot and API server automatically detect the running model via `MLX_MODEL_ID`.

---

## BI Module (Olist Dataset)

The `duckclaw.bi` module includes ready-to-use business intelligence functions for the Olist e-commerce dataset.

```python
import duckclaw
from duckclaw.bi import load_olist_data, get_top_customers_by_sales, get_top_sellers

db = duckclaw.DuckClaw("olist_bi.duckdb")
load_olist_data(db, "data")           # Load all CSVs from data/ folder

get_top_customers_by_sales(db, limit=15)
get_top_sellers(db, limit=15)
```

Available functions: `get_top_customers_by_sales`, `get_customers_to_retain`, `get_top_sellers`, `get_delivery_metrics`, `get_delivery_critical_cases`, `get_sales_summary`, `get_review_metrics`, `get_category_sales`.

### Natural language queries

```python
from duckclaw.bi import ask_bi
respuesta = ask_bi(db, "¿Cuáles son los vendedores con más retrasos?", provider="mlx")
print(respuesta)
```

Supported providers: `groq` (`GROQ_API_KEY`), `deepseek` (`DEEPSEEK_API_KEY`), `mlx` (local).

---

## Project Structure

```
duckclaw/
├── duckclaw/
│   ├── agents/
│   │   ├── telegram_bot.py      # Telegram bot (LangGraph + bicameral memory)
│   │   ├── general_graph.py     # LangGraph graph with DuckDB tools
│   │   ├── graph_server.py      # FastAPI server for LangSmith Studio
│   │   ├── router.py            # Entry router graph
│   │   └── tools.py             # run_sql, inspect_schema, manage_memory
│   ├── bi/                      # BI functions (Olist dataset)
│   ├── integrations/
│   │   ├── telegram.py          # Telegram base class
│   │   └── llm_providers.py     # LLM provider factory (build_llm)
│   ├── ops/
│   │   ├── cli.py               # duckops CLI
│   │   └── manager.py           # deploy / status / serve
│   └── utils/
│       └── format.py            # Reply formatting, tool output helpers
├── scripts/
│   ├── duckclaw_setup_wizard.py # Interactive setup wizard
│   └── install_duckclaw.sh      # One-line installer
├── mlx/
│   └── start_mlx.sh             # MLX inference server launcher
├── ecosystem.core.config.cjs    # PM2 config for Telegram bot
├── ecosystem.config.cjs         # PM2 config for MLX inference
├── langgraph.json               # LangGraph Studio config
└── .env                         # Environment variables (git-ignored)
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

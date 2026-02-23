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

## License

MIT License. See LICENSE for more information.
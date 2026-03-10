# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

DuckClaw is a C++17/pybind11 native extension over DuckDB with a Python AI agent framework (LangGraph). See `README.md` for full docs.

### Build & dependency management

- Package manager: **uv** (`uv.lock` present). Run `uv sync --extra all --extra dev --extra agents --extra serve --extra groq --extra huggingface --extra ollama` to install all development dependencies.
- The C++ extension (`_duckclaw.so`) requires **cmake**, **g++**, **pybind11**, and a DuckDB shared library. The prebuilt DuckDB v1.1.3 for Linux x86_64 is installed at `/usr/local/duckdb`.
- **Critical ABI note:** The prebuilt DuckDB library uses the old GCC ABI. You must pass `CMAKE_ARGS="-DDUCKDB_ROOT=/usr/local/duckdb -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++ -DCMAKE_CXX_FLAGS=-D_GLIBCXX_USE_CXX11_ABI=0"` when building (the update script handles this).
- System prerequisites already installed in the VM snapshot: `libstdc++-13-dev`, `python3.12-dev`, and the `libstdc++.so` symlink at `/usr/lib/x86_64-linux-gnu/libstdc++.so`.

### Running tests and checks

- **Tests:** `uv run pytest tests/ -v` — 60 tests, all pure-Python (no external services needed).
- **Type checking:** `uv run mypy duckclaw/` — should report zero issues.
- **Core smoke test:** `uv run python tests/test_duckclaw.py` — verifies C++ extension loads and queries DuckDB.

### Running the API Gateway (dev mode)

```bash
uv run uvicorn duckclaw.api.gateway:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI at `http://localhost:8000/docs`. Does not require an LLM provider.

### Running the LangGraph API Server

Requires `DUCKCLAW_LLM_PROVIDER` set in `.env` or environment (e.g. `openai`, `deepseek`, `none_llm`). Without a valid LLM provider, the server will error at startup.

```bash
uv run python -m duckclaw.agents.graph_server --port 8123
```

### Running the Telegram Bot

Requires `TELEGRAM_BOT_TOKEN` and a configured LLM provider. See `README.md` for env vars.

### Key gotchas

- The default system `c++` is **clang** on the VM, which cannot find the C++ standard library headers. Always set `CC=gcc CXX=g++` when building the extension.
- DuckDB is embedded (file-based `.duckdb` files) — no external database service needed.
- The `none_llm` provider enables rules-only mode for the LangGraph agent (useful for testing without API keys).

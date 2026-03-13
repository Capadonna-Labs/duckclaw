# DuckClaw 🦆⚔️

**High-performance C++ analytical memory layer for sovereign AI agents.**

Optimized for Cross-Platform (Win/Lin/Mac) · Multi-tenant · Microservices Ready · Powered by DuckDB

---

## Architecture (Monorepo)

DuckClaw is now organized as a modular monorepo to support high scalability and independent deployments.

```
duckclaw/
├── packages/               # Lógica modular
│   ├── core/              # DuckDB Native (C++)
│   ├── agents/            # LangGraph & Workers
│   └── shared/            # Utils, CLI & Integrations
├── services/              # Microservicios
│   ├── api-gateway/       # FastAPI Gateway
│   └── db-writer/         # Singleton Writer Bridge
├── config/                # Centralización de configuración
├── data/                  # Datalake & Databases
├── docker/                # Multi-stage Dockerfiles
└── specs/                 # Technical Specs (SDM)
```

## Key Components

- **Singleton Writer Bridge**: Prevents DuckDB write locks by queuing all modifications in Redis.
- **API Gateway**: Decouples network/auth from agent logic, supporting SSE streaming.
- **Cross-Platform CLI**: `duckops` (Python-based) manages services on Linux, Windows, and macOS.

## Testing the Singleton Writer Pipeline

The end-to-end flow **API Gateway → Redis → DB Writer → DuckDB** is specified in `specs/04_Singleton_Writer_Pipeline.md` and validated by:

- **Unit tests** (contract + gateway behavior):

  ```bash
  uv run pytest tests/run_singleton_writer_pipeline.py -v -m "not integration"
  ```

- **Optional integration test** (requires Redis running on `localhost:6379`, e.g. `docker run -d --name duckclaw-redis -p 6379:6379 redis:7-alpine`):

  ```bash
  RUN_SINGLETON_PIPELINE_INTEGRATION=1 uv run pytest tests/run_singleton_writer_pipeline.py -v -m integration
  ```

## Quick Start (Docker)

```bash
docker build -t duckclaw-base -f docker/base/Dockerfile .
docker build -t duckclaw-api -f docker/api/Dockerfile .
```

## Spec-Driven Management (SDM)

This project follows **SDM**. No feature is implemented without an approved specification in `specs/`.

---
Built by [IoTCoreLabs](https://iotcorelabs.io)

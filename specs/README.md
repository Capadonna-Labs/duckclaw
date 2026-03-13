# Especificaciones DuckClaw

Las **especificaciones consolidadas** del proyecto son estas cinco:

| Archivo | Contenido |
|---------|-----------|
| **00_System_Infrastructure.md** | Monorepo, Tailscale, API Gateway, PM2/Docker, CI/CD, inferencia elástica, resiliencia. |
| **01_Analytical_Memory_Architecture.md** | Motores híbridos (DuckDB, Redis), PGQ/GraphRAG, Vector RAG, Arrow Zero-Copy, persistencia, CRM bicameral. |
| **02_Skills_and_Tooling_Framework.md** | Research (Tavily, Browser-Use), Sandbox Strix, GitHub MCP, Context Hub, On-the-Fly CLI, ingesta multimodal. |
| **03_Cognitive_Agent_Logic.md** | Homeostasis, Worker Factory, Subagent Spawning (Send/SSE), HITL, memory windowing, Fact-Checker, Model-Guard, QuoteEngine, SFT/MLX. |
| **04_Singleton_Writer_Pipeline.md** | Flujo API Gateway → Redis → DB Writer → DuckDB; tests de pipeline (`tests/run_singleton_writer_pipeline.py`) y comandos de verificación (pytest + Redis Docker). |

Los directorios `layer_*` y `feature/`, así como los archivos sueltos en la raíz de `specs/`, son el **origen** del contenido fusionado; pueden usarse como referencia o detalle histórico. Para trabajo normativo usar siempre **00–04**.
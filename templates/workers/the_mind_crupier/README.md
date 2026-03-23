# The Mind — crupier (copia de referencia)

Esta carpeta replica el template canónico en el código:

`packages/agents/src/duckclaw/forge/templates/TheMindCrupier/`

El **id de template** que usa el runtime de DuckClaw es **`TheMindCrupier`** (véase `manifest.yaml`).

Para añadir el worker al chat: `/workers --add TheMindCrupier`.

Los **fly commands** (`/new_mind`, `/join`, `/start_mind`, `/play`) se ejecutan en el API Gateway contra la **bóveda DuckDB activa** del usuario, sin pasar por el LLM.

# Layer 2: Framework de Herramientas y Habilidades (Skills)

Define cómo los agentes interactúan con el entorno: investigación autónoma, sandbox de ejecución, GitHub MCP, CLI dinámico, Context Hub (Ground Truth de APIs), seguridad y auditoría.

---

## 1. Ecosistema de Herramientas (Universal Skills)

### Investigación autónoma (Tavily + Browser-Use)

- **TavilySearch**: búsqueda web en tiempo real; `search_depth="advanced"`, `include_answer=True`; post-procesamiento en Validator para fuentes y relevancia.
- **BrowserUse**: navegación autónoma (Playwright); el agente genera pasos (click, extraer tabla); ejecución **obligatoria dentro del Sandbox Strix** para aislar el navegador.
- **ResearchAgent**: orquesta Tavily → Browser-Use → síntesis; salida `ResearchReport` (hallazgos + fuentes). Perfil de navegador limpio por sesión; whitelist de dominios en sandbox; registro en LangSmith.

### Sandbox de ejecución (Strix)

- Entorno Turing-completo (Python/Bash/SQL) en contenedor, sin acceso al host ni a `duckclaw.db`.
- **Imagen**: `ghcr.io/usestrix/strix-sandbox` (o derivado con pandas, duckdb). Red aislada, `--cap-drop=ALL`, límites cgroups.
- **Flujo seguro**: Host ejecuta `SELECT` aprobado → exporta a `/tmp/session_id/data.parquet` → montaje solo lectura en contenedor (`/workspace/data`); salida en `/workspace/output`.
- **StrixSandboxRunner**: provisioning por `session_id`, envío de `script_content`, timeout, captura stdout/stderr, recuperación de artefactos. Bucle de auto-corrección: si exit code ≠ 0, agente analiza error y reescribe código.
- Auditoría: cada ejecución registrada (latencia, evidencia) en DuckDB.

### GitHub MCP

- Agente de ingeniería: leer código, crear issues (p. ej. por fallos del GRPO_Evaluator), PRs con mejoras.
- **Skill GitHubEngineeringSkill**: servidor MCP (`npx @modelcontextprotocol/server-github`) vía stdio; herramientas `read_file`, `create_issue`, `search_code` en SkillRegistry. Repos permitidos definidos en `manifest.yaml`.
- Token con scope solo al repo; HITL para acciones destructivas (`delete_branch`, `merge_pr`) vía `/approve` en Telegram.

### Context Hub (Ground Truth de APIs)

- **Propósito**: Evitar alucinaciones al integrar o consultar APIs externas; documentación oficial/actualizada.
- **Skill ContextHubBridge**: herramienta que ejecuta CLI `chub get {api_name}/{resource} --lang python`; salida como texto (markdown/JSON) al contexto del agente. Si falla: "Documentación no encontrada en Context Hub. Procede con precaución."
- **Contrato**: entradas `api_name` (obligatorio), `resource` (opcional, p. ej. `docs`, `openapi`). Requiere `chub` en PATH; opcional `CONTEXT_HUB_API_KEY`, `CONTEXT_HUB_BASE_URL`.
- Uso: Planner o subagente invoca ContextHubBridge **antes** de generar código o llamadas a la API; resultado se inyecta en prompt o estado del grafo.

---

## 2. Interfaz dinámica (On-the-Fly CLI)

CLI `duckops` para control administrativo y mutación de estado en caliente (sin reiniciar PM2).

- **`/role <worker_id>`**: cambia rol del agente; pausa thread, carga `manifest.yaml` del nuevo rol, actualiza system_prompt y tools, confirma.
- **`/skills`**: lista herramientas habilitadas (nombre y descripción).
- **`/forget`**: borra historial del chat en checkpointer y ventana de contexto; registra supresión (Habeas Data).
- **`/context on|off`**: activa/desactiva inyección de RAG (memoria a largo plazo) en el prompt.
- **`/audit`**: muestra última evidencia (SQL, tiempo, tokens, run_id LangSmith).
- **`/health`**: estado de inferencia (MLX/llama.cpp), DuckDB, latencia/RAM.
- **`/approve` | `/reject`**: autoriza o deniega operación retenida por SQLValidator o SandboxPipeline (grafo en `interrupt`).

Enrutamiento: en `telegram_bot` (o equivalente), parsear comandos que empiezan por `/` antes de invocar LangGraph.

---

## 3. Seguridad y aislamiento

- **Vaulting**: secretos inyectados en runtime, nunca en disco en claro.
- **Auditoría**: cada ejecución de herramienta con latencia y evidencia en DuckDB; trazabilidad forense.
- **Sandbox**: sin acceso a BD de producción; datos solo vía export controlado (Parquet) en solo lectura.
- **Scope de tokens**: GitHub MCP y APIs externas con permisos mínimos; HITL para acciones destructivas.

---

## 4. Ingestión multimodal (voz y visión)

- **API**: `POST /api/v1/agent/{worker_id}/media/{thread_id}` (multipart: audio/ogg, image/jpeg). Guardado en `/tmp/duckclaw_media/{uuid}`; cola ARQ para procesamiento.
- **AudioTranscriber**: Whisper (MLX en Apple Silicon); salida texto en `<audio_transcription>`; borrado seguro del archivo (Habeas Data).
- **VisionInterpreter**: modelo visión edge (p. ej. mlx-vlm); salida en `<image_description>`. Opción tmpfs para media en RAM; solo texto en LangSmith, nunca binario.

---

*Consolidado desde: Pipeline_de_Investigación_y_Navegacion_Autonoma_(Tavily+Browser-Use), Sandbox_de_Ejecucion_Libre_Basado_en_Strix, Integracion_de_GitHub_MCP_en_DuckClaw, interfaz_de_comandos_dinamicos_On-the-Fly_CLI, Subagent Spawning & Context Hub (ContextHubBridge), Pipeline_Ingestion_Multimodal_Voz_Vision.*

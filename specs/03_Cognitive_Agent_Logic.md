# Layer 3: Lógica Cognitiva y Agentes Inteligentes

Consolidación de la arquitectura de razonamiento, ciclo de vida de agentes, homeostasis, subagent spawning, validación (Fact-Checker, Model-Guard), HITL, memory windowing y motor de cotización.

---

## 1. Arquitectura de Agentes Homeostáticos (Active Inference)

Agentes que mantienen "salud" minimizando incertidumbre en su dominio.

- **Estado interno (Beliefs)**: tabla `agent_beliefs` por worker (p. ej. Finanz: `presupuesto_mensual`, `tasa_ahorro_objetivo`; Engineer: `cobertura_tests_minima`).
- **HomeostasisNode**: en cada ciclo: (1) Percepción, (2) Cálculo de Sorpresa vs beliefs, (3) Si sorpresa alta → acción de restauración, (4) Actualización de beliefs.
- **HomeostasisManager** (skill): entrada `belief_key`, `observed_value`; si `delta > threshold` → `Action_Restore_Homeostasis`, si no → `Action_Maintain_Equilibrium`.
- Plantillas en `forge/templates/` pueden incluir `homeostasis.yaml` (beliefs, thresholds, actions por trigger). Auditoría: consultar `agent_beliefs` para explicar decisiones.

---

## 2. Worker Factory y Plantillas

Instanciación de trabajadores virtuales por plantilla declarativa.

- **Estructura**: `templates/workers/<worker_id>/` con `manifest.yaml`, `system_prompt.md`, `schema.sql`, `skills/` (módulos Python).
- **WorkerFactory**: entrada `worker_id`, `telegram_chat_id`; lee manifest, ejecuta schema en DuckDB (esquema aislado), carga system_prompt en Planner, inyecta tools de `skills/` en Executor; salida grafo LangGraph compilado con checkpointer.
- **WorkerCLI**: `duckops hire <worker_id> --name <instance_name>` → valida plantilla, genera `.env.<instance_name>`, actualiza ecosystem.config.cjs, `pm2 start`.
- **Roster típico**: FinanzWorker (Planner→Executor→SQLValidator→Explainer; insert_transaction, get_monthly_summary, categorize_expense); SupportWorker (RAG_Retriever, solo lectura; search_knowledge_base, get_ticket_status). Aislamiento: un `thread_id` por instancia; auditoría con `worker_role`, `instance` en LangSmith; skills de código dinámico vía SandboxPipeline.

---

## 3. Subagent Spawning (LangGraph Send)

Para peticiones complejas (p. ej. "Cotízame 50 abrazaderas y envía resumen a mi socio"), el agente principal no ejecuta secuencialmente: delega subtareas en paralelo.

- **Planner**: convierte petición en lista `todos` (task_id, description, tooling_context, parallelizable, priority).
- **SubAgentSpawner**: recibe `todos` y **retorna lista de `Send(subgraph_name, payload)`** (LangGraph v0.2+). No usa `asyncio.gather`; paralelismo, reintentos y persistencia los gestiona el runtime de LangGraph.
- **Subgrafos**: p. ej. `quote_subgraph`, `email_subgraph`; cada uno recibe payload con task_id, description, correlation_id, user.
- **Aggregator**: combina resultados parciales en respuesta final.
- **Observabilidad (SSE)**: el Gateway emite `subagents_started` (con lista de tasks), `subagents_updated` (estado por task_id), `subagents_finished`; Angular (ParallelTaskIndicatorComponent) consume el stream para mostrar "Ejecutando N tareas en paralelo...". Endpoint: `GET /api/v1/agent/subagents/stream?session_id=...`; eventos publicados vía `POST /api/v1/agent/subagents/event`.

---

## 4. Protocolo HITL (Handoff a humano)

Transferencia determinista agente ↔ operador; estado en Redis.

- **Estados**: IDLE, BUSY, HANDOFF_REQUESTED, MANUAL_MODE. Clave `session_state:{thread_id}` (status, context_summary, requested_at).
- **HandoffTrigger** (skill): reason, context_summary → Redis HANDOFF_REQUESTED, webhook n8n, HandoffInterrupt en el grafo. Criterios: RAG miss en 2 turnos, sentimiento de frustración/urgencia, petición explícita ("asesor", "humano", "llamar").
- **API**: si MANUAL_MODE → respuesta `{"status": "ignored", "reason": "manual_mode_active"}`; `POST .../thread/{thread_id}/takeover` → MANUAL_MODE; `POST .../thread/{thread_id}/release` → IDLE (inyecta historial humano); `GET .../thread/{thread_id}/status`. author_type AI|HUMAN en auditoría; DataMasker en mensajes humanos antes de inyectar en memoria.

---

## 5. Memory Windowing (Ventana de contexto)

Qué parte del historial se inyecta en cada turno (por turnos o, en futuro, por tokens).

- **Fuentes**: system_prompt, history (últimos N turnos desde BD), incoming (mensaje actual). Ventana = subconjunto de history enviado al modelo.
- **Política**: sliding por turnos; por defecto 10 turnos con RAG activo, 3 con `/context off`. Exclusión de mensajes que empiezan por `/`. Historial completo en BD; ventana solo para construcción de `state["history"]`.
- **Comandos**: `/context on|off` (cambia límite); `/forget` (borra historial del chat y registra supresión). Futuro: límite por tokens y summarization de turnos antiguos.

---

## 6. RAG Fact-Checker (Context-Guard)

Garantizar que la respuesta no invente datos respecto a la evidencia recuperada.

- **FactCheckerNode**: entrada `user_query`, `raw_evidence`, `draft_response`. Extrae afirmaciones críticas (SKU, precios, etc.); LLM-as-a-Judge verifica entailment contra raw_evidence; FactualityScore; salida `ValidationResult` (is_safe, correction_feedback).
- **SelfCorrectionNode**: si `is_safe: false`, incrementa `correction_retries`; si > 2 → HandoffTrigger; si no, reescritura con feedback. Prompt de corrección estricto.
- **Config**: `context_guard.enabled`, `max_retries` en manifest. Trazabilidad: evento `hallucination_prevented` en LangSmith; trazas aprobadas en primer intento para SFT_DataCollector.

---

## 7. Model-Guard (Evaluación pre-despliegue)

Gatekeeper entre entrenamiento (SFT) y producción (Hot-Swap).

- **ModelEvaluator**: entrada modelo finetuned + `golden_dataset.jsonl`. Inferencia de prueba, validación con SQLValidator y StrixSandbox, métricas (Accuracy, LogicScore), comparativa con modelo actual; salida EvaluationReport + Decision (Promote/Abort).
- **Versionado**: directorios `models/active`, `models/vN_timestamp`, `models/archive`; Hot-Swap actualiza symlink `active` y SIGHUP a inferencia; si Abort, alerta por Telegram. Golden dataset con consultas sintéticas (no datos reales).

---

## 8. Motor de Cotización Omnicanal (QuoteEngine)

Cotizaciones agnósticas al canal de entrega.

- **QuoteEngine**: entrada items (SKU, cantidades), user_id; validación en catálogo, reglas (descuentos, IVA 19%), persistencia en tabla quotes; salida QuoteData (JSON).
- **DocumentDispatcher**: genera PDF en /tmp/quotes/, empaqueta payload, invoca N8N_QUOTE_WEBHOOK_URL; n8n enruta por Email, WhatsApp, etc. sin cambiar código del agente.
- **API**: `GET /api/v1/quotes/download/{quote_id}` con token un solo uso o auth; FileResponse PDF; auditoría de descarga.

---

## 9. Pipeline de entrenamiento (SFT con MLX)

- **SFT_DataCollector**: reemplaza GRPO; trazas LangSmith con reward 1.0 → extracción input/output, anonimización (DataMasker), formato ChatML, validación sqlglot; salida `dataset_sft.jsonl`.
- **MLX_SFT_Trainer**: SFT sobre Llama-3.2-3B con LoRA (rank 8, alpha 16); salida adapters; fusión y conversión a GGUF para Hot-Swap sin downtime. Evaluación con Model-Guard antes de promover.

---

*Consolidado desde: Estandar_de_Agentes_Homeostaticos, sistema_de_plantillas_de_agentes_virtual_worker_factory, Protocolo_Escalamiento_Humano_HITL_Handoff, gestion_de_ventana_de_contexto_memory_windowing, Pipeline_de_Evaluacion_y_Validación_de_Modelos_(Model-Guard), Subagent Spawning & Context Hub (Planner, Send, Aggregator, SSE), RAG_Fact_Checker_Context_Guard, Motor_Cotizacion_Omnicanal_QuoteEngine, Migracion_de_Pipeline_de_Entrenamiento_(GRPO_a_SFT_con_MLX).*

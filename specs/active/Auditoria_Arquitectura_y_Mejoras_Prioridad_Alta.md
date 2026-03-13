# Auditoría de Arquitectura y Puntos de Mejora (Prioridad Alta)

Especificación técnica para mitigar riesgos críticos identificados en la arquitectura DuckClaw.

---

## 1. Vulnerabilidad de Concurrencia (DuckDB Write Locks)

### Estado Actual

La integración de ARQ (Redis) y FastAPI permite procesamiento asíncrono y concurrente. DuckDB usa un modelo **multi‑lector, un solo escritor**. Las escrituras concurrentes provocan colisiones de bloqueo.

### Riesgo Crítico

`duckdb.IOException: Could not set lock on file` → pérdida de datos o caída del worker cuando FinanzWorker registra transacciones mientras HomeostasisManager actualiza `agent_beliefs`.

### Especificación: SingletonWriterBridge

| Componente | Descripción |
|------------|-------------|
| **Desacoplamiento** | Lecturas directas; escrituras en cola única |
| **Cola** | Redis `duckdb_write_queue` (LIST) para todas las sentencias INSERT/UPDATE |
| **Consumidor** | Proceso único `DuckClaw-DB-Writer` en PM2, ejecuta escrituras secuencialmente |
| **API** | `db.execute()` en agentes → `enqueue_write(sql)` → Redis LPUSH |

**Ver:** `duckclaw/forge/homeostasis/manager.py`, `duckclaw/agents/tools.py` (run_sql, manage_memory).

---

## 2. Resiliencia y Recuperación ante Desastres

### Estado Actual

Datos en Mac Mini (DuckDB, modelos GGUF, adaptadores LoRA). Sin plan de recuperación ante fallos de hardware.

### Riesgo Crítico

Pérdida total del historial financiero, memoria PGQ y progreso SFT tras fallo físico del nodo.

### Especificación: DisasterRecoveryNode

| Paso | Acción |
|------|--------|
| 1 | Cronjob (n8n/PM2) → snapshot diario de `duckclaw.db` y `models/active/` |
| 2 | Cifrado local con Restic o SOPS (AES-256-GCM) |
| 3 | Sincronización hacia Cloudflare R2 o AWS S3 con Object Lock |
| 4 | Datos ilegibles sin llave privada local aunque el bucket sea comprometido |

**Script:** `scripts/disaster_recovery.sh` (ver sección 4).

---

## 3. Gestión Dinámica de Secretos (Zero-Trust Vaulting)

### Estado Actual

Variables de entorno (.env) para credenciales: `IBKR_PORTFOLIO_API_KEY`, `TELEGRAM_BOT_TOKEN`, `X-Tailscale-Auth-Key`.

### Riesgo Crítico

Filtrado por core dumps, logs mal configurados o procesos hijos en StrixSandbox si el aislamiento falla.

### Especificación: SecretVaultManager

| Requisito | Implementación |
|-----------|----------------|
| Eliminar .env en producción | Integrar Mozilla SOPS o HashiCorp Vault (modo dev) |
| Inyección en runtime | Forge inyecta secretos en memoria del proceso Python |
| Borrado seguro | `del` + `gc.collect()` tras la skill tras usar el secreto |

---

## 4. Monitoreo de Deriva Semántica (Post-Deployment Drift)

### Estado Actual

ModelEvaluator valida contra Golden Dataset antes del Hot-Swap. No hay protección tras el deploy si el modelo alucina con datos reales no previstos.

### Riesgo Crítico

Decisiones homeostáticas erróneas por interpretaciones degradadas del contexto financiero.

### Especificación: ShadowInferenceRouter

| Fase | Comportamiento |
|------|----------------|
| Ventana 48h post Hot-Swap | Gateway envía prompt al modelo nuevo (activo) y, en background, al modelo anterior (archivo) |
| Comparación | Similitud coseno entre embeddings de ambas respuestas |
| Umbral | Si divergencia > 15% en tareas de extracción de entidades financieras → alerta n8n + rollback automático |

---

## Implementación de Referencia

- **SingletonWriterBridge:** `duckclaw/forge/homeostasis/singleton_writer.py`
- **Disaster Recovery:** `scripts/disaster_recovery.sh`
- **SecretVault:** stub en `duckclaw/forge/secret_vault.py`
- **ShadowInference:** stub en `duckclaw/forge/shadow_inference.py`

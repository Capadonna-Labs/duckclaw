Esta es la **Roadmap de Producción (Fase 1: Estabilización y Despliegue)**. El objetivo es pasar de un sistema funcional en desarrollo a una plataforma autónoma, auditable y lista para el primer cliente (Power Seal).

---

# Roadmap: DuckClaw Production Readiness (Corto Plazo)

## Prioridad 1: Estabilidad y Seguridad (Hardening)
*El sistema debe ser invulnerable antes de procesar datos reales.*

1.  **Implementación del `SecurityGateway` (Nodo de Validación):**
    *   **Acción:** Integrar `sqlglot` en el nodo `SQLValidator` para asegurar que el agente solo ejecute `SELECT` y `INSERT` autorizados.
    *   **Acción:** Implementar el `DataMasker` en el `AuditMiddleware` del API Gateway para anonimizar PII (tarjetas, emails) antes de persistir logs en LangSmith.
2.  **Hardening del VPS:**
    *   **Acción:** Ejecutar `scripts/hardening.sh` (configuración de firewall UFW, SSH keys, cifrado de partición con LUKS).
    *   **Acción:** Configurar `systemd` para el contenedor de `n8n` y `Postgres` (asegurando persistencia).

## Prioridad 2: Orquestación y Disponibilidad (Gateway + n8n)
*El sistema debe ser capaz de gestionar múltiples tareas y reportar su estado.*

3.  **Implementación del `ActivityManager` (Redis + ARQ):**
    *   **Acción:** Configurar Redis en el VPS.
    *   **Acción:** Migrar el endpoint `/chat` de FastAPI para que encole tareas en `ARQ` en lugar de ejecutar el grafo de forma síncrona.
    *   **Acción:** Implementar el registro de estados (`IDLE`, `BUSY`, `WAITING`) en Redis para que Angular y n8n puedan consultar la disponibilidad.
4.  **Conectividad (Tailscale Mesh):**
    *   **Acción:** Finalizar la configuración de la Tailnet entre Mac Mini y VPS.
    *   **Acción:** Validar que el `n8n_bridge` pueda disparar flujos desde el agente hacia el VPS de forma segura.

## Prioridad 3: Entrenamiento y Calidad (SFT Pipeline)
*El sistema debe aprender de sus éxitos y auto-validarse.*

5.  **Pipeline SFT (MLX):**
    *   **Acción:** Implementar el `SFT_DataCollector` para extraer trazas exitosas de LangSmith.
    *   **Acción:** Crear el script `train_sft.py` (MLX-native) para fine-tuning supervisado.
    *   **Acción:** Implementar el `ModelEvaluator` (Model-Guard) para validar el modelo antes del `Hot-Swap`.
6.  **Limpieza de Deuda Técnica:**
    *   **Acción:** Eliminar `tests/test_grpo_rewards.py` y reemplazarlo por `tests/test_sft_data_collector.py`.

## Prioridad 4: Integración de Negocio (Power Seal)
*El sistema debe ser útil para el cliente final.*

7.  **SupportWorker (Power Seal):**
    *   **Acción:** Crear la plantilla `templates/workers/powerseal/`.
    *   **Acción:** Inyectar el catálogo de productos (vía RAG o System Prompt).
    *   **Acción:** Configurar el `HomeostasisManager` para que el agente sea proactivo (ej. "Si el cliente pregunta por X, y no hay stock, ofrecer Y").
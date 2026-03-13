# Migración de Pipeline de Entrenamiento (GRPO a SFT con MLX)

## 1. Objetivo Arquitectónico
Eliminar la lógica de aprendizaje por refuerzo (GRPO) y consolidar un pipeline de **Supervised Fine-Tuning (SFT)** nativo para **MLX**. El sistema debe aprender exclusivamente de trazas validadas (Reward=1.0) en LangSmith, garantizando que el modelo local (Llama-3.2-3B) converja hacia patrones de razonamiento aprobados por el `SQLValidator` y el `StrixSandbox`.

## 2. Especificación de Skill: `SFT_DataCollector` (MLX-Native)
Este nodo reemplaza al `GRPO_Evaluator`. Su función es transformar trazas de LangSmith en un dataset de entrenamiento supervisado.

*   **Entrada:** Trazas de LangSmith (`reward == 1.0`).
*   **Lógica:**
    1.  **Extracción:** Obtener `input` (prompt) y `output` (código/SQL generado).
    2.  **Anonimización:** Aplicar `DataMasker` para eliminar PII (nombres, tarjetas, direcciones).
    3.  **Formateo ChatML:**
        ```json
        {"text": "<s>[INST] <<SYS>>\nEres un asistente financiero experto.\n<</SYS>>\n{prompt} [/INST] {code} </s>"}
        ```
    4.  **Validación:** Ejecutar `sqlglot` sobre el campo `code` para asegurar que el SQL es sintácticamente correcto antes de incluirlo en el dataset.
*   **Salida:** `dataset_sft.jsonl` (formato compatible con `mlx-lm`).

## 3. Especificación de Skill: `MLX_SFT_Trainer`
Este script reemplaza la lógica de GRPO por un entrenamiento supervisado eficiente.

*   **Entrada:** `dataset_sft.jsonl`, Modelo Base (`Llama-3.2-3B-Instruct`).
*   **Lógica:**
    1.  **Carga:** `mlx_lm.load` (modelo en 4-bit).
    2.  **Configuración LoRA:**
        *   `rank`: 8, `alpha`: 16.
        *   `target_modules`: `q_proj`, `v_proj`, `k_proj`, `o_proj`.
    3.  **Entrenamiento:** `mlx_lm.train` (SFT).
        *   `batch_size`: 1 (para maximizar uso de memoria unificada).
        *   `learning_rate`: 2e-5.
        *   `epochs`: 1.
*   **Salida:** `adapters.npz` (pesos LoRA).

## 4. Especificación de Test: `tests/test_sft_data_collector.py`
Este test reemplaza al fallido `test_grpo_rewards.py`.

*   **Lógica:**
    1.  **Mocking:** Crear un objeto `Trace` con datos financieros ficticios.
    2.  **Anonimización:** Verificar que el `DataMasker` reemplaza datos sensibles por `[MASKED]`.
    3.  **Formato:** Verificar que el JSONL resultante cumple con el template `<s>[INST]...[/INST]...</s>`.
    4.  **Sintaxis:** Verificar que el SQL extraído es parseable por `sqlglot`.
*   **Resultado:** `True` (Dataset listo para entrenamiento).

## 5. Protocolo de Hot-Swap (MLX)
Para evitar downtime, el proceso de inferencia no se detiene:

1.  **Entrenamiento:** El `MLX_SFT_Trainer` genera `adapters.npz`.
2.  **Fusión:** El script ejecuta `mlx_lm.fuse` para integrar los adaptadores en el modelo base.
3.  **Conversión:** El script ejecuta `mlx_lm.convert` para generar un nuevo `model_finetuned.gguf`.
4.  **Señal:** El script envía `SIGHUP` al proceso `DuckClaw-Inference` (PM2).
5.  **Recarga:** El servidor de inferencia detecta el cambio en el archivo `.gguf` y recarga el modelo en memoria.

## 6. Eliminación de Deuda Técnica
*   **Limpieza:** Eliminar `tests/test_grpo_rewards.py`.
*   **Refactorización:** Eliminar cualquier referencia a `reward_functions` en `duckclaw/agents/`.
*   **CI/CD:** Actualizar `.github/workflows/deploy.yml` para ejecutar `pytest tests/test_sft_data_collector.py` en lugar del test de GRPO.
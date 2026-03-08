# Trazas para entrenamiento (SFT por defecto, GRPO alternativa)

Este directorio almacena trazas en formato JSONL. El **pipeline por defecto** es **SFT** (Supervised Fine-Tuning) con MLX. GRPO (Group Relative Policy Optimization) sigue disponible como alternativa.

## Pipeline SFT (por defecto)

### 1. Guardar trazas

```python
from duckclaw.bi import ask_bi, load_olist_data
import duckclaw

db = duckclaw.DuckClaw("olist_bi.duckdb")
load_olist_data(db, "data")
respuesta = ask_bi(db, "¿Mejores vendedores?", provider="groq", save_traces=True)
```

### 2. Clasificar rewards y generar dataset SFT

```python
from duckclaw.rl import classify_traces
from duckclaw.forge.sft import collect_traces_to_sft

# Clasificar trazas (escribe grpo_olist_rewarded.jsonl)
classify_traces()

# Generar dataset SFT (dataset_sft.jsonl) — solo trazas con reward 1.0
records, stats = collect_traces_to_sft()
print("SFT:", stats)  # total_output, skipped_sql, skipped_reward
```

### 3. Entrenar con MLX

```bash
# Requiere: pip install "mlx-lm[train]"
python mlx/train_sft.py
```

Salida: `train/adapters/` (LoRA).

### 4. Model-Guard y Hot-Swap

Antes del hot-swap, `mlx_hotswap.sh` ejecuta **Model-Guard** (`scripts/eval_model.py`): evalúa el modelo contra `golden_dataset.jsonl` (Accuracy: SQL válido). Si accuracy >= 95%, procede con el hot-swap; si no, aborta y alerta por Telegram.

```bash
./scripts/mlx_hotswap.sh
```

Evaluación manual (con DuckDB para LogicScore):

```bash
python scripts/eval_model.py --model train/model_finetuned --db-path olist.duckdb
```

---

## Pipeline GRPO (alternativa)

Para entrenamiento GRPO con Unsloth u otros frameworks que requieren múltiples completions por prompt:

```python
from duckclaw.rl import classify_traces, convert_to_grpo_groups

classify_traces()
groups, stats = convert_to_grpo_groups()
```

Salida: `train/grpo_olist_groups.jsonl` (solo prompts con ≥2 completions).

---

## Formato de trazas

Cada línea es un objeto JSON:

```json
{
  "prompt": "¿Quiénes son los mejores vendedores?",
  "completion": "<thought>...</thought>\n<tool_call>...</tool_call>\n<answer>...</answer>",
  "messages": [
    {"role": "user", "content": "¿Quiénes son los mejores vendedores?"},
    {"role": "assistant", "content": "<thought>...</thought>..."}
  ],
  "metadata": {"timestamp": "...", "provider": "groq", "source": "ask_bi"}
}
```

- **prompt**: pregunta del usuario.
- **completion**: respuesta del modelo en formato XML estructurado (thought, tool_call, answer).
- **messages**: formato chat para entrenamiento.
- **metadata**: timestamp, provider (groq/mlx), source.

## API directa

```python
from duckclaw.bi.grpo_traces import save_grpo_trace, load_grpo_traces, trace_stats

save_grpo_trace("¿Cuál es el tiempo de entrega?", "<thought>...</thought>...", provider="mlx")
traces = load_grpo_traces(limit=100)  # Por defecto carga grpo_olist_rewarded.jsonl
print(trace_stats())
```

## LangSmith

Para enviar trazas a [LangSmith](https://smith.langchain.com/):

1. Crea `.env` con `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`
2. `save_traces=True, send_to_langsmith=True` en `ask_bi` o `save_grpo_trace`

## Criterios de reward (clasificación)

- Formato: `<thought>`, `<tool_call>`, `<answer>` en orden (+0.25)
- JSON válido en tool_call (+0.25)
- Tools válidas (+0.25)
- Sin artefactos `<|eot_id|>` (+0.1)
- Coherencia prompt→herramienta (+0.15)

## Archivos

| Archivo | Descripción |
|---------|-------------|
| `grpo_olist_traces.jsonl` | Trazas crudas. Entrada de `classify_traces()`. |
| `grpo_olist_rewarded.jsonl` | Formato grupos con rewards. Entrada de `collect_traces_to_sft()` y `convert_to_grpo_groups()`. |
| **`dataset_sft.jsonl`** | **Dataset de entrenamiento SFT por defecto.** Formato ChatML. Salida de `collect_traces_to_sft()`. |
| `grpo_olist_groups.jsonl` | Alternativa GRPO: solo prompts con ≥2 completions. Para Unsloth. |
| `adapters/` | Pesos LoRA tras `mlx/train_sft.py`. |
| `model_finetuned/` | Modelo fusionado tras `scripts/mlx_hotswap.sh`. |
| **`golden_dataset.jsonl`** | **Golden dataset para Model-Guard.** 10-20 consultas sintéticas validadas. |

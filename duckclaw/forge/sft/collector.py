"""
SFT_DataCollector — transforma trazas con reward 1.0 en dataset SFT (ChatML).

Spec: specs/Migracion_de_Pipeline_de_Entrenamiento_(GRPO_a_SFT_con_MLX).md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from duckclaw.forge.sft.datamasker import DataMasker
from duckclaw.rl.rewards import _parse_tool_calls_from_completion

TRAIN_DIR = Path(__file__).resolve().parents[3] / "train"
DEFAULT_INPUT_PATH = TRAIN_DIR / "grpo_olist_rewarded.jsonl"
DEFAULT_SFT_DATASET_PATH = TRAIN_DIR / "dataset_sft.jsonl"
DEFAULT_SYSTEM_PROMPT = "Eres un asistente financiero experto."


def _validate_sql_in_completion(completion: str) -> bool:
    """
    Extrae SQL de tool_call args (clave 'sql') y valida con sqlglot.
    Retorna True si no hay SQL o si todo el SQL es válido; False si hay SQL inválido.
    """
    try:
        import sqlglot
    except ImportError:
        return True  # Sin sqlglot, no validar
    tool_calls = _parse_tool_calls_from_completion(completion)
    for tc in tool_calls:
        args = tc.get("args") or {}
        sql = args.get("sql")
        if not sql or not isinstance(sql, str):
            continue
        sql = sql.strip()
        if not sql:
            continue
        try:
            sqlglot.parse(sql, dialect="duckdb")
        except Exception:
            return False
    return True


def collect_traces_to_sft(
    input_path: Optional[Path | str] = None,
    output_path: Optional[Path | str] = None,
    *,
    system_prompt: Optional[str] = None,
    min_reward: float = 1.0,
    datamasker: Optional[DataMasker] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Convierte trazas con reward >= min_reward en dataset SFT (formato ChatML).

    - input_path: JSONL grupos (default: train/grpo_olist_rewarded.jsonl).
    - output_path: salida JSONL (default: train/dataset_sft.jsonl).
    - system_prompt: texto para <<SYS>> (default: "Eres un asistente financiero experto.").
    - min_reward: solo incluir completions con reward >= min_reward (default 1.0).
    - datamasker: instancia para anonimizar; si None, se crea una.

    Retorna (lista de registros SFT escritos, estadísticas).
    """
    inp = Path(input_path) if input_path else DEFAULT_INPUT_PATH
    out = Path(output_path) if output_path else DEFAULT_SFT_DATASET_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    sys_prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT).strip()
    masker = datamasker or DataMasker()

    if not inp.exists():
        return [], {
            "input_path": str(inp),
            "output_path": str(out),
            "total_output": 0,
            "skipped_sql": 0,
            "skipped_reward": 0,
        }

    records: list[dict[str, Any]] = []
    skipped_sql = 0
    skipped_reward = 0

    with open(inp, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                group = json.loads(line)
            except json.JSONDecodeError:
                continue
            prompt = (group.get("prompt") or "").strip()
            completions = group.get("completions") or []
            for c in completions:
                reward = float(c.get("reward", -1))
                if reward < min_reward:
                    skipped_reward += 1
                    continue
                text = c.get("text") or ""
                if not text.strip():
                    continue
                if not _validate_sql_in_completion(text):
                    skipped_sql += 1
                    continue
                prompt_masked = masker.mask(prompt)
                completion_masked = masker.mask(text)
                chatml = (
                    f"<s>[INST] <<SYS>>\n{sys_prompt}\n<</SYS>>\n"
                    f"{prompt_masked} [/INST] {completion_masked} </s>"
                )
                records.append({"text": chatml})

    with open(out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    stats = {
        "input_path": str(inp),
        "output_path": str(out),
        "total_output": len(records),
        "skipped_sql": skipped_sql,
        "skipped_reward": skipped_reward,
    }
    return records, stats

"""
SFT_DataCollector — transforma trazas con reward 1.0 en dataset SFT (ChatML).

Spec: specs/Migracion_de_Pipeline_de_Entrenamiento_(GRPO_a_SFT_con_MLX).md
Spec: DuckClaw Production Readiness — extracción desde LangSmith.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
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


def collect_from_langsmith(
    project_name: Optional[str] = None,
    output_path: Optional[Path | str] = None,
    *,
    start_time: Optional[datetime] = None,
    limit: int = 500,
    min_reward: float = 1.0,
    system_prompt: Optional[str] = None,
    datamasker: Optional[DataMasker] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Extrae trazas exitosas de LangSmith y las convierte a dataset SFT.

    - project_name: Proyecto LangSmith (default: LANGSMITH_PROJECT o LANGCHAIN_PROJECT).
    - output_path: Salida JSONL (default: train/dataset_sft.jsonl).
    - start_time: Desde cuándo extraer (default: últimas 24h).
    - limit: Máximo de runs a procesar.
    - min_reward: Solo runs sin error (reward=1.0 si success).
    """
    try:
        from langsmith import Client
    except ImportError:
        return [], {
            "error": "langsmith no instalado. pip install langsmith",
            "total_output": 0,
            "skipped_sql": 0,
            "skipped_reward": 0,
        }

    project = project_name or os.environ.get("LANGSMITH_PROJECT") or os.environ.get("LANGCHAIN_PROJECT", "")
    if not project:
        return [], {
            "error": "LANGSMITH_PROJECT o project_name requerido",
            "total_output": 0,
            "skipped_sql": 0,
            "skipped_reward": 0,
        }

    since = start_time or (datetime.now(timezone.utc) - timedelta(days=1))
    out = Path(output_path) if output_path else DEFAULT_SFT_DATASET_PATH
    out.parent.mkdir(parents=True, exist_ok=True)

    client = Client()
    groups: dict[str, dict[str, Any]] = {}

    try:
        runs = client.list_runs(
            project_name=project,
            start_time=since,
            limit=limit,
            is_root=True,
            error=False,
        )
        for run in runs:
            inputs = run.inputs or {}
            outputs = run.outputs or {}
            prompt = ""
            if isinstance(inputs, dict):
                for k in ("messages", "incoming", "message", "input", "prompt"):
                    if k in inputs:
                        v = inputs[k]
                        if isinstance(v, str):
                            prompt = v
                            break
                        if isinstance(v, list) and v:
                            msg = v[-1] if isinstance(v[-1], dict) else v[-1]
                            prompt = str(msg.get("content", msg) if isinstance(msg, dict) else msg)
                            break
            if not prompt:
                prompt = str(inputs)[:2000]

            completion = ""
            if isinstance(outputs, dict):
                for k in ("output", "reply", "content", "content", "result"):
                    if k in outputs:
                        completion = str(outputs[k])
                        break
            if not completion:
                completion = str(outputs)[:2000]

            if not prompt.strip() or not completion.strip():
                continue

            key = prompt[:100]
            if key not in groups:
                groups[key] = {"prompt": prompt, "completions": []}
            groups[key]["completions"].append({"text": completion, "reward": 1.0})
    except Exception as e:
        return [], {
            "error": str(e),
            "total_output": 0,
            "skipped_sql": 0,
            "skipped_reward": 0,
        }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for g in groups.values():
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
        tmp_path = f.name

    try:
        records, stats = collect_traces_to_sft(
            input_path=tmp_path,
            output_path=out,
            system_prompt=system_prompt,
            min_reward=min_reward,
            datamasker=datamasker,
        )
        stats["source"] = "langsmith"
        stats["project"] = project
        return records, stats
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

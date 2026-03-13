"""
ModelEvaluator — gatekeeper entre entrenamiento SFT y hot-swap.

Spec: specs/Pipeline_de_Evaluacion_y_Validacion_de_Modelos_(Model-Guard).md

Ejecuta golden dataset contra el modelo candidato, valida SQL (sqlglot) y
ejecución lógica (DuckDB/BI tools). Retorna EvaluationReport + Decision.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

TRAIN_DIR = Path(__file__).resolve().parents[3] / "train"
DEFAULT_GOLDEN_PATH = TRAIN_DIR / "golden_dataset.jsonl"
DEFAULT_SYSTEM_PROMPT = "Eres un asistente financiero experto."
ACCURACY_THRESHOLD = 0.95


def load_golden_dataset(path: Optional[Path | str] = None) -> list[dict[str, Any]]:
    """Carga golden_dataset.jsonl. Cada línea: {prompt, expected_tool?}."""
    p = Path(path) if path else DEFAULT_GOLDEN_PATH
    if not p.exists():
        return []
    items: list[dict[str, Any]] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def _validate_sql_in_completion(completion: str) -> bool:
    """Valida SQL en tool_call args con sqlglot. Reutiliza lógica de SFT collector."""
    from duckclaw.rl.rewards import _parse_tool_calls_from_completion

    try:
        import sqlglot
    except ImportError:
        return True
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


def _run_inference(model_path: str, prompt: str, system_prompt: str, max_tokens: int = 512) -> str:
    """Carga modelo MLX y genera completion para el prompt."""
    from mlx_lm import generate, load

    model, tokenizer = load(model_path)
    chatml = (
        f"<s>[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n"
        f"{prompt} [/INST] "
    )
    response = generate(model, tokenizer, prompt=chatml, max_tokens=max_tokens, verbose=False)
    raw = str(getattr(response, "generated_text", response)) if not isinstance(response, str) else response
    # Extraer solo el completion (después de [/INST])
    if "[/INST]" in raw:
        raw = raw.split("[/INST]", 1)[-1]
    return raw.strip()


def _execute_tool_calls(db: Any, completion: str, tools_by_name: dict[str, Any]) -> bool:
    """
    Ejecuta cada tool_call contra DuckDB/BI. Retorna True si todos pasan.
    """
    from duckclaw.rl.rewards import _parse_tool_calls_from_completion

    tool_calls = _parse_tool_calls_from_completion(completion)
    if not tool_calls:
        return True  # Sin tool calls, no hay nada que ejecutar
    for tc in tool_calls:
        name = tc.get("tool")
        args = tc.get("args") or {}
        if not name or name not in tools_by_name:
            return False
        try:
            result = tools_by_name[name].invoke(args)
            if isinstance(result, str) and result.startswith("Error"):
                return False
        except Exception:
            return False
    return True


def evaluate_model(
    model_path: str,
    golden_dataset: Optional[list[dict[str, Any]]] = None,
    *,
    db: Optional[Any] = None,
    data_dir: Optional[str] = None,
    golden_path: Optional[Path | str] = None,
    system_prompt: Optional[str] = None,
    threshold: float = ACCURACY_THRESHOLD,
    max_tokens: int = 512,
) -> tuple[bool, dict[str, Any]]:
    """
    Ejecuta golden dataset contra el modelo y retorna (promote, report).

    - model_path: ruta al modelo fusionado (directorio MLX o HuggingFace)
    - golden_dataset: lista de {prompt, expected_tool?}; si None, carga desde golden_path
    - db: DuckClaw/DuckDB con datos Olist para LogicScore; si None, solo Accuracy
    - data_dir: directorio con CSV Olist para load_olist_data (ej. "data")
    - golden_path: ruta a golden_dataset.jsonl si golden_dataset es None
    - system_prompt: prompt de sistema (default BI)
    - threshold: umbral de accuracy para Promote (default 0.95)
    - max_tokens: máximo de tokens por generación

    Retorna (promote: bool, report: dict).
    """
    items = golden_dataset if golden_dataset is not None else load_golden_dataset(golden_path)
    if not items:
        return False, {
            "accuracy": 0.0,
            "logic_score": 0.0,
            "decision": "Abort",
            "reason": "golden_dataset_vacio",
            "results": [],
        }

    sys_prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT).strip()
    tools_by_name: dict[str, Any] = {}
    if db is not None:
        try:
            if data_dir:
                from duckclaw.bi import load_olist_data

                load_olist_data(db, data_dir, skip_missing=True)
        except Exception:
            pass
        try:
            from duckclaw.bi.agent import build_olist_bi_tools

            tools = build_olist_bi_tools(db)
            tools_by_name = {t.name: t for t in tools}
        except Exception:
            tools_by_name = {}

    results: list[dict[str, Any]] = []
    accuracy_ok = 0
    logic_ok = 0  # Contador de ejecuciones exitosas (solo si tools_by_name)

    for i, item in enumerate(items):
        prompt = (item.get("prompt") or "").strip()
        if not prompt:
            results.append({"index": i, "prompt": "", "accuracy_ok": False, "logic_ok": False, "error": "prompt_vacio"})
            continue

        try:
            completion = _run_inference(model_path, prompt, sys_prompt, max_tokens=max_tokens)
        except Exception as e:
            results.append({"index": i, "prompt": prompt[:80], "accuracy_ok": False, "logic_ok": False, "error": str(e)})
            continue

        acc_ok = _validate_sql_in_completion(completion)
        if acc_ok:
            accuracy_ok += 1

        exec_ok = False
        if tools_by_name:
            exec_ok = _execute_tool_calls(db, completion, tools_by_name)
            if exec_ok:
                logic_ok += 1
        else:
            exec_ok = True  # Sin db, no evaluamos LogicScore

        results.append({
            "index": i,
            "prompt": prompt[:80],
            "accuracy_ok": acc_ok,
            "logic_ok": exec_ok,
        })

    n = len(items)
    accuracy = accuracy_ok / n if n else 0.0
    if tools_by_name:
        logic_score = logic_ok / n if n else 0.0
        logic_ok_count = logic_ok
    else:
        logic_score = 1.0
        logic_ok_count = n

    promote = accuracy >= threshold
    decision = "Promote" if promote else "Abort"

    report = {
        "accuracy": round(accuracy, 4),
        "logic_score": round(logic_score, 4),
        "decision": decision,
        "threshold": threshold,
        "total": n,
        "accuracy_ok": accuracy_ok,
        "logic_ok_count": logic_ok_count if tools_by_name else n,
        "results": results,
    }

    # LangSmith
    _langsmith_log(report)

    # Telegram en Abort
    if not promote:
        _telegram_alert(report)

    return promote, report


def _langsmith_log(report: dict[str, Any]) -> None:
    """Registra EvaluationReport en LangSmith para auditoría."""
    try:
        api_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
        if not api_key or os.environ.get("LANGCHAIN_TRACING_V2", "").lower() not in ("true", "1"):
            return
        from langsmith import Client

        client = Client(api_key=api_key)
        client.create_run(
            name="model_guard_evaluation",
            run_type="chain",
            inputs={"model_guard": True},
            outputs=report,
            tags=["system_validation", "model_guard"],
        )
    except Exception:
        pass


def _telegram_alert(report: dict[str, Any]) -> None:
    """Envía alerta al administrador vía Telegram en Abort."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("MODEL_GUARD_ALERT_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    msg = (
        f"Entrenamiento fallido: degradación de precisión detectada. "
        f"Accuracy: {report.get('accuracy', 0):.2%}, LogicScore: {report.get('logic_score', 0):.2%}"
    )
    try:
        import urllib.request
        import urllib.parse

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as _:
            pass
    except Exception:
        pass

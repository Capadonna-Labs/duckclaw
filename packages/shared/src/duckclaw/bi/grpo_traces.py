"""
Trazas XML en JSONL listas para entrenamiento GRPO (Group Relative Policy Optimization).

- grpo_olist_traces.jsonl: formato flat (prompt, completion, messages, metadata).
- grpo_olist_rewarded.jsonl: formato grupos {"prompt": "...", "completions": [{"text": "...", "reward": 1.0}]}.
  Nuevas trazas se fusionan por prompt (normalizado). Requerido para GRPO/Unsloth.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Directorio por defecto para trazas
TRAIN_DIR = Path(__file__).resolve().parents[2] / "train"
DEFAULT_TRACE_FILE = TRAIN_DIR / "grpo_olist_traces.jsonl"
# Por defecto para usar/cargar: rewarded (ya tiene rewards, listo para entrenar)
DEFAULT_REWARDED_FILE = TRAIN_DIR / "grpo_olist_rewarded.jsonl"

# Proyecto LangSmith por defecto para trazas GRPO
LANGSMITH_PROJECT = os.environ.get("LANGCHAIN_PROJECT", "duckclaw-grpo")


def _ensure_train_dir() -> Path:
    """Asegura que existe el directorio train/."""
    TRAIN_DIR.mkdir(parents=True, exist_ok=True)
    return TRAIN_DIR


def _normalize_prompt_for_grouping(prompt: str) -> str:
    """Normaliza prompt para agrupar variantes (cuántas/cuantas, mayúsculas, etc.)."""
    if not prompt:
        return ""
    s = prompt.strip().lower()
    for old, new in [("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")]:
        s = s.replace(old, new)
    return " ".join(s.split())


def _load_dotenv() -> None:
    """Carga .env en os.environ si existe (para notebooks que no heredan variables)."""
    for base in (Path.cwd(), Path(__file__).resolve().parents[2]):
        env_file = base / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1].replace('\\"', '"')
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1].replace("\\'", "'")
                        if key:
                            os.environ.setdefault(key, value)
            except Exception:
                pass
            break


def _send_to_langsmith(
    prompt: str,
    completion: str,
    metadata: dict[str, Any],
) -> bool:
    """Envía una traza a LangSmith. Requiere LANGCHAIN_API_KEY (o LANGSMITH_API_KEY)."""
    _load_dotenv()
    api_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        return False
    try:
        from langsmith.run_helpers import trace, tracing_context

        # tracing_context(enabled=True) fuerza el envío aunque LANGSMITH_TRACING no esté en .env
        with tracing_context(enabled=True, project_name=LANGSMITH_PROJECT):
            with trace(
                "grpo_olist_trace",
                run_type="chain",
                inputs={"prompt": prompt},
                project_name=LANGSMITH_PROJECT,
                metadata=metadata,
            ) as run:
                run.end(outputs={"completion": completion})
        return True
    except Exception as e:
        import warnings
        warnings.warn(f"LangSmith: no se pudo enviar traza: {e}", UserWarning)
        return False


def save_grpo_trace(
    prompt: str,
    completion: str,
    *,
    output_path: Optional[Path | str] = None,
    provider: str = "",
    source: str = "ask_bi",
    metadata: Optional[dict[str, Any]] = None,
    send_to_langsmith: bool = False,
) -> Path:
    """
    Guarda una traza en JSONL lista para GRPO.

    - prompt: pregunta del usuario (input).
    - completion: respuesta del modelo en formato XML estructurado
      (<thought>, <tool_call>, <answer>) o texto crudo.
    - output_path: ruta al archivo .jsonl (por defecto train/grpo_olist_traces.jsonl).
    - provider, source: metadatos opcionales.
    - send_to_langsmith: si True, envía la traza a LangSmith (requiere LANGCHAIN_API_KEY).
    """
    path = Path(output_path) if output_path else DEFAULT_TRACE_FILE
    _ensure_train_dir()
    meta = dict(metadata or {})
    meta.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
    meta.setdefault("provider", provider)
    meta.setdefault("source", source)
    record = {
        "prompt": prompt,
        "completion": completion,
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": completion},
        ],
        "metadata": meta,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    if send_to_langsmith:
        _send_to_langsmith(prompt, completion, meta)
    # Clasificar y merge en rewarded.jsonl (formato grupos GRPO)
    try:
        from duckclaw.rl.rewards import compute_reward
        reward, breakdown = compute_reward(record)
        rewarded_path = DEFAULT_REWARDED_FILE
        _ensure_train_dir()
        # Leer grupos existentes (soporta formato flat legacy)
        groups_dict: dict[str, dict[str, Any]] = {}
        if rewarded_path.exists():
            with open(rewarded_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if "completions" in rec:
                            key = _normalize_prompt_for_grouping(rec.get("prompt", ""))
                            if key:
                                groups_dict[key] = rec
                        else:
                            p = (rec.get("prompt") or "").strip()
                            c = rec.get("completion") or ""
                            r = float(rec.get("reward", 0))
                            key = _normalize_prompt_for_grouping(p)
                            if key:
                                groups_dict[key] = {"prompt": p, "completions": [{"text": c, "reward": r}]}
                    except json.JSONDecodeError:
                        continue
        # Merge nueva completion
        key = _normalize_prompt_for_grouping(prompt)
        new_comp = {"text": completion, "reward": reward}
        if key in groups_dict:
            groups_dict[key]["completions"].append(new_comp)
        else:
            groups_dict[key] = {"prompt": prompt.strip(), "completions": [new_comp]}
        # Enriquecer (dedup, contraste, mínimo 2 con rewards diferentes)
        try:
            from duckclaw.rl.rewards import _enrich_groups_for_grpo
            groups_list = _enrich_groups_for_grpo(list(groups_dict.values()))
        except Exception:
            groups_list = list(groups_dict.values())
        with open(rewarded_path, "w", encoding="utf-8") as f:
            for g in groups_list:
                f.write(json.dumps(g, ensure_ascii=False) + "\n")
    except Exception:
        pass  # No fallar si rl no está disponible o hay error
    return path


def load_grpo_traces(
    path: Optional[Path | str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Carga trazas desde un archivo JSONL.

    - path: ruta al .jsonl (por defecto train/grpo_olist_rewarded.jsonl, formato grupos).
      Para trazas crudas usa DEFAULT_TRACE_FILE o "train/grpo_olist_traces.jsonl".
    - limit: máximo de líneas (grupos) a cargar (None = todas).
    """
    p = Path(path) if path else DEFAULT_REWARDED_FILE
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(p, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def trace_stats(path: Optional[Path | str] = None) -> dict[str, Any]:
    """Estadísticas del archivo de trazas (rewarded en formato grupos)."""
    traces = load_grpo_traces(path)
    providers: dict[str, int] = {}
    total_completions = 0
    for t in traces:
        if "completions" in t:
            total_completions += len(t["completions"])
        else:
            total_completions += 1
            prov = (t.get("metadata") or {}).get("provider", "unknown")
            providers[prov] = providers.get(prov, 0) + 1
    return {
        "total": total_completions,
        "groups": len(traces),
        "providers": providers if providers else {},
        "path": str(Path(path) if path else DEFAULT_REWARDED_FILE),
    }

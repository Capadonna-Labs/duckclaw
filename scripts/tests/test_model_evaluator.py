"""Tests for Model-Guard (forge/eval)."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from duckclaw.forge.eval import evaluate_model, load_golden_dataset


def test_load_golden_dataset() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"prompt": "¿Mejores vendedores?", "expected_tool": "get_top_sellers"}\n')
        f.write('{"prompt": "¿Qué tablas hay?"}\n')
        path = Path(f.name)
    try:
        items = load_golden_dataset(path)
        assert len(items) == 2
        assert items[0]["prompt"] == "¿Mejores vendedores?"
        assert items[0]["expected_tool"] == "get_top_sellers"
        assert items[1]["prompt"] == "¿Qué tablas hay?"
        assert "expected_tool" not in items[1] or items[1].get("expected_tool") is None
    finally:
        path.unlink(missing_ok=True)


def test_load_golden_dataset_empty_path() -> None:
    items = load_golden_dataset("/nonexistent/path.jsonl")
    assert items == []


def test_evaluate_model_mock_promote() -> None:
    """Con mock de inferencia que retorna completion válido, debe Promote."""
    golden = [
        {"prompt": "¿Mejores vendedores?"},
        {"prompt": "¿Qué tablas hay?"},
    ]
    valid_completion = (
        '<thought>Análisis...</thought>\n'
        '<tool_call>{"tool": "get_top_sellers", "args": {"limit": 10}}</tool_call>\n'
        '<answer>Consultando...</answer>'
    )

    def fake_inference(model_path, prompt, system_prompt, max_tokens=512):
        return valid_completion

    with patch("duckclaw.forge.eval.model_evaluator._run_inference", side_effect=fake_inference):
        promote, report = evaluate_model(
            "/fake/model",
            golden_dataset=golden,
            db=None,
            threshold=0.95,
        )
    assert promote is True
    assert report["decision"] == "Promote"
    assert report["accuracy"] == 1.0
    assert report["total"] == 2


def test_evaluate_model_mock_abort() -> None:
    """Con mock que retorna SQL inválido, debe Abort."""
    golden = [{"prompt": "Exporta a Excel"}]
    invalid_completion = (
        '<thought>X</thought>\n'
        '<tool_call>{"tool": "export_to_excel", "args": {"sql": "SELEC * FROM olist_orders", "sheet_name": "x", "limit": 10}}</tool_call>\n'
        '<answer>Ok</answer>'
    )

    def fake_inference(model_path, prompt, system_prompt, max_tokens=512):
        return invalid_completion

    with patch("duckclaw.forge.eval.model_evaluator._run_inference", side_effect=fake_inference):
        promote, report = evaluate_model(
            "/fake/model",
            golden_dataset=golden,
            db=None,
            threshold=0.95,
        )
    assert promote is False
    assert report["decision"] == "Abort"
    assert report["accuracy"] == 0.0


def test_evaluate_model_golden_path() -> None:
    """Carga desde archivo golden_dataset."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"prompt": "¿Tablas?"}\n')
        path = Path(f.name)
    try:
        def fake_inference(model_path, prompt, system_prompt, max_tokens=512):
            return '<thought>X</thought>\n<tool_call>{"tool": "list_tables", "args": {}}</tool_call>\n<answer>Ok</answer>'

        with patch("duckclaw.forge.eval.model_evaluator._run_inference", side_effect=fake_inference):
            promote, report = evaluate_model(
                "/fake/model",
                golden_dataset=None,
                golden_path=path,
                db=None,
            )
        assert report["total"] == 1
        assert "accuracy" in report
    finally:
        path.unlink(missing_ok=True)

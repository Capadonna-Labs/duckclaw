"""Tests for SFT DataCollector (forge/sft)."""

import json
import tempfile
from pathlib import Path

from duckclaw.forge.sft import DataMasker, collect_traces_to_sft


def test_datamasker_emails() -> None:
    masker = DataMasker()
    text = "Contacto: user@example.com o admin@corp.co"
    assert "[MASKED]" in masker.mask(text)
    assert "user@example.com" not in masker.mask(text)
    assert "admin@corp.co" not in masker.mask(text)


def test_datamasker_credit_cards() -> None:
    masker = DataMasker()
    text = "Tarjeta 1234-5678-9012-3456 o 1234 5678 9012 3456"
    assert "[MASKED]" in masker.mask(text)
    assert "1234-5678-9012-3456" not in masker.mask(text)


def test_chatml_format() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(
            json.dumps({
                "prompt": "¿Mejores vendedores?",
                "completions": [{
                    "text": '<thought>X</thought>\n<tool_call>{"tool": "get_top_sellers", "args": {"limit": 10}}</tool_call>\n<answer>Ok</answer>',
                    "reward": 1.0,
                }],
            }, ensure_ascii=False) + "\n"
        )
        inp = Path(f.name)
    out = inp.parent / "dataset_sft_test.jsonl"
    try:
        records, stats = collect_traces_to_sft(input_path=inp, output_path=out)
        assert len(records) == 1
        text = records[0]["text"]
        assert text.startswith("<s>[INST] <<SYS>>")
        assert "<</SYS>>" in text
        assert "[/INST]" in text
        assert text.endswith("</s>")
        assert "Eres un asistente financiero experto" in text
    finally:
        inp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def test_sql_valid_included() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(
            json.dumps({
                "prompt": "Exporta ventas a Excel",
                "completions": [{
                    "text": '<thought>Exportaré</thought>\n<tool_call>{"tool": "export_to_excel", "args": {"sql": "SELECT * FROM olist_orders LIMIT 100", "sheet_name": "datos", "limit": 100}}</tool_call>\n<answer>Listo</answer>',
                    "reward": 1.0,
                }],
            }, ensure_ascii=False) + "\n"
        )
        inp = Path(f.name)
    out = inp.parent / "dataset_sft_sql_valid.jsonl"
    try:
        records, stats = collect_traces_to_sft(input_path=inp, output_path=out)
        assert len(records) == 1
        assert stats["skipped_sql"] == 0
    finally:
        inp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def test_sql_invalid_excluded() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(
            json.dumps({
                "prompt": "Exporta ventas",
                "completions": [{
                    "text": '<thought>X</thought>\n<tool_call>{"tool": "export_to_excel", "args": {"sql": "SELECT FROM invalid syntax here", "sheet_name": "x", "limit": 10}}</tool_call>\n<answer>Ok</answer>',
                    "reward": 1.0,
                }],
            }, ensure_ascii=False) + "\n"
        )
        inp = Path(f.name)
    out = inp.parent / "dataset_sft_sql_invalid.jsonl"
    try:
        records, stats = collect_traces_to_sft(input_path=inp, output_path=out)
        assert len(records) == 0
        assert stats["skipped_sql"] == 1
    finally:
        inp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def test_min_reward_filter() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(
            json.dumps({
                "prompt": "Pregunta",
                "completions": [
                    {"text": "<thought>X</thought>\n<tool_call>{\"tool\": \"list_tables\", \"args\": {}}</tool_call>\n<answer>Ok</answer>", "reward": 0.5},
                    {"text": "<thought>Y</thought>\n<tool_call>{\"tool\": \"list_tables\", \"args\": {}}</tool_call>\n<answer>Ok</answer>", "reward": 1.0},
                ],
            }, ensure_ascii=False) + "\n"
        )
        inp = Path(f.name)
    out = inp.parent / "dataset_sft_reward.jsonl"
    try:
        records, stats = collect_traces_to_sft(input_path=inp, output_path=out, min_reward=1.0)
        assert len(records) == 1
        assert stats["skipped_reward"] == 1
    finally:
        inp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)

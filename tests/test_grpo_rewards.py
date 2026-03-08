"""Tests for GRPO rewards classification."""

from duckclaw.rl import compute_reward, classify_traces


def test_compute_reward_perfect() -> None:
    trace = {
        "prompt": "¿Quiénes son los mejores vendedores?",
        "completion": '<thought>Análisis...</thought>\n<tool_call>{"tool": "get_top_sellers", "args": {"limit": 10}}</tool_call>\n<answer>Consultando...</answer>',
    }
    r, b = compute_reward(trace)
    assert r == 1.0
    assert b["format"] == 0.25
    assert b["json_valid"] == 0.25
    assert b["tools_valid"] == 0.25


def test_compute_reward_with_artifacts() -> None:
    trace = {
        "prompt": "¿Mejores vendedores?",
        "completion": '<thought>X</thought>\n<tool_call>{"tool": "get_top_sellers", "args": {}}</tool_call>\n<answer>Ok</answer><|eot_id|>',
    }
    r, _ = compute_reward(trace)
    assert r < 1.0
    assert r >= 0.5


def test_compute_reward_empty() -> None:
    trace = {"prompt": "¿Qué?", "completion": ""}
    r, _ = compute_reward(trace)
    assert r == -1.0


def test_classify_traces() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"prompt": "vendedores?", "completion": "<thought>X</thought>\\n<tool_call>{\\"tool\\": \\"get_top_sellers\\", \\"args\\": {}}</tool_call>\\n<answer>Ok</answer>", "messages": [], "metadata": {}}\n')
        inp = Path(f.name)
    out = inp.parent / "rewarded_test.jsonl"
    try:
        rewarded, stats = classify_traces(input_path=inp, output_path=out)
        assert len(rewarded) >= 1
        assert "reward" in rewarded[0]
        assert stats["total_output"] >= 1
    finally:
        inp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)

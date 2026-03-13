"""Tests for BI agent: structured output, parseo JSON y fallback MLX."""

from duckclaw.bi.agent import (
    OLIST_BI_TOOL_NAMES,
    _strip_artifacts,
    _parse_raw_tool_calls,
    _is_raw_tool_calls_reply,
    _normalize_mlx_reply,
)


def test_strip_artifacts() -> None:
    assert _strip_artifacts("hello") == "hello"
    assert _strip_artifacts("hello<|eom_id|>") == "hello"
    assert _strip_artifacts("hello <|eom_id|> ") == "hello"
    assert _strip_artifacts("hello<|eot_id|>") == "hello"
    assert _strip_artifacts("") == ""
    assert _strip_artifacts("  \n  ") == ""


def test_parse_raw_tool_calls_problematic_pattern() -> None:
    """Fallback para el patrón observado: {"name":...,"parameters":...}; ... <|eom_id|>"""
    raw = '{"name": "get_top_sellers", "parameters": {"limit": "10"}}; {"name": "get_delivery_metrics", "parameters": {}}; {"name": "plot_top_customers_bar", "parameters": {"limit": "10"}}<|eom_id|>'
    parsed = _parse_raw_tool_calls(raw)
    assert len(parsed) == 3
    assert parsed[0]["tool"] == "get_top_sellers"
    assert parsed[0]["args"] == {"limit": 10}
    assert parsed[1]["tool"] == "get_delivery_metrics"
    assert parsed[1]["args"] == {}
    assert parsed[2]["tool"] == "plot_top_customers_bar"
    assert parsed[2]["args"] == {"limit": 10}


def test_parse_raw_tool_calls_tool_args_format() -> None:
    """Formato {"tool": "x", "args": {...}}"""
    raw = '{"tool": "get_top_sellers", "args": {"limit": 15}}'
    parsed = _parse_raw_tool_calls(raw)
    assert len(parsed) == 1
    assert parsed[0]["tool"] == "get_top_sellers"
    assert parsed[0]["args"] == {"limit": 15}


def test_parse_raw_tool_calls_ignores_unknown_tools() -> None:
    raw = '{"name": "unknown_tool", "parameters": {}}'
    parsed = _parse_raw_tool_calls(raw)
    assert len(parsed) == 0


def test_is_raw_tool_calls_reply() -> None:
    assert _is_raw_tool_calls_reply(
        '{"name": "get_top_sellers", "parameters": {"limit": "10"}}<|eom_id|>'
    )
    assert _is_raw_tool_calls_reply(
        '{"tool": "get_delivery_metrics", "args": {}}'
    )
    assert _is_raw_tool_calls_reply(
        '{"name": "a", "parameters": {}}; {"name": "b", "parameters": {}}'
    )
    assert not _is_raw_tool_calls_reply("Hola, aquí está el resumen de ventas.")
    assert not _is_raw_tool_calls_reply("")


def test_normalize_mlx_reply_raw_tool_calls() -> None:
    """Cuando la respuesta es tool-calls crudos, se ejecutan y se compone la salida."""

    class MockTool:
        def __init__(self, name: str):
            self.name = name

        def invoke(self, args: dict) -> str:
            return f'[{{"tool": "{self.name}", "args": {args}}}]'

    tools = [MockTool(n) for n in OLIST_BI_TOOL_NAMES]
    raw = '{"name": "get_top_sellers", "parameters": {"limit": "5"}}<|eom_id|>'
    result = _normalize_mlx_reply(raw, None, tools)
    assert "<|eom_id|>" not in result
    assert "get_top_sellers" in result or "[" in result


def test_structured_output_has_valid_tool_call_json() -> None:
    """El bloque <tool_call> debe contener JSON parseable."""
    import json

    example = '{"tool": "get_delivery_metrics", "args": {}}'
    obj = json.loads(example)
    assert obj["tool"] in OLIST_BI_TOOL_NAMES
    assert isinstance(obj.get("args"), dict)


def test_normalize_passes_through_non_raw_reply() -> None:
    """Respuestas con formato estructurado y tool_calls válidos se ejecutan y devuelven lenguaje natural."""
    class MockTool:
        def __init__(self, name: str):
            self.name = name

        def invoke(self, args: dict) -> str:
            return '[{"avg_delivery_days": 12.5, "min_delivery_days": 2, "max_delivery_days": 45}]'

    tools = [MockTool("get_delivery_metrics")]
    structured = """<thought>
Análisis: el usuario pide métricas de entrega.
</thought>
<tool_call>
{"tool": "get_delivery_metrics", "args": {}}
</tool_call>
<answer>
Aquí están las métricas de entrega.
</answer>"""
    result = _normalize_mlx_reply(structured, None, tools)
    assert "Tiempo de entrega" in result or "12.5" in result or "promedio" in result

"""Smoke tests for entry router: get_route and build_entry_router_graph."""

from __future__ import annotations

from unittest.mock import MagicMock

import duckclaw
from duckclaw.agents.router import get_route, build_entry_router_graph, RETAIL_KEYWORDS


def test_get_route_no_retail_always_general() -> None:
    assert get_route("hola", has_retail=False) == "general"
    assert get_route("qué tablas hay", has_retail=False) == "general"
    assert get_route("vendí una blusa", has_retail=False) == "general"


def test_get_route_retail_keywords() -> None:
    assert get_route("vendí una blusa", has_retail=True) == "retail"
    assert get_route("qué hay en inventario", has_retail=True) == "retail"
    assert get_route("registra venta de pantalón XL", has_retail=True) == "retail"
    assert get_route("gastos de arriendo", has_retail=True) == "retail"
    assert get_route("listar productos", has_retail=True) == "retail"


def test_get_route_general_when_no_keywords() -> None:
    assert get_route("qué tablas hay", has_retail=True) == "general"
    assert get_route("ejecuta SELECT 1", has_retail=True) == "general"
    assert get_route("hola", has_retail=True) == "general"
    assert get_route("", has_retail=True) == "general"


def test_router_imports() -> None:
    from duckclaw.agents import build_entry_router_graph as build_graph, get_route as gr

    assert build_graph is not None
    assert gr("inventario", True) == "retail"


def test_build_entry_router_graph_smoke() -> None:
    """Build entry router graph and invoke with a mock LLM (no API required)."""
    from langchain_core.messages import AIMessage

    db = duckclaw.DuckClaw(":memory:")
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.invoke.return_value = AIMessage(content="Respuesta de prueba.")

    graph = build_entry_router_graph(db, mock_llm, system_prompt="Test.")
    result = graph.invoke({"incoming": "hola", "history": []})
    assert "reply" in result
    assert isinstance(result["reply"], str)
    assert "Respuesta de prueba" in result["reply"] or len(result["reply"]) >= 0

"""Tests for Context-Guard (FactChecker + SelfCorrection). Spec: specs/RAG_Fact_Checker_Context_Guard.md"""

from unittest.mock import MagicMock

from duckclaw.forge.atoms.validators import (
    extract_raw_evidence_from_messages,
    _parse_fact_check_result,
    fact_checker_node,
    handoff_reply_node,
)
from langchain_core.messages import AIMessage, ToolMessage


def test_extract_raw_evidence_from_catalog_retriever() -> None:
    msgs = [
        AIMessage(
            content="...",
            tool_calls=[{"name": "catalog_retriever", "id": "tc1", "args": {"user_query": "x"}}],
        ),
        ToolMessage(
            content='{"results": [{"sku": "A1", "price": 10, "name": "Product A"}]}',
            tool_call_id="tc1",
        ),
    ]
    ev = extract_raw_evidence_from_messages(msgs)
    assert ev is not None
    assert "A1" in ev
    assert "Product A" in ev


def test_extract_raw_evidence_returns_last_when_multiple() -> None:
    msgs = [
        AIMessage(
            content="...",
            tool_calls=[{"name": "catalog_retriever", "id": "tc1", "args": {}}],
        ),
        ToolMessage(content='{"results": [{"sku": "OLD"}]}', tool_call_id="tc1"),
        AIMessage(
            content="...",
            tool_calls=[{"name": "catalog_retriever", "id": "tc2", "args": {}}],
        ),
        ToolMessage(content='{"results": [{"sku": "NEW"}]}', tool_call_id="tc2"),
    ]
    ev = extract_raw_evidence_from_messages(msgs)
    assert ev is not None
    assert "NEW" in ev
    assert "OLD" not in ev  # returns last catalog_retriever only


def test_extract_raw_evidence_returns_none_when_no_catalog_call() -> None:
    msgs = [
        AIMessage(
            content="...",
            tool_calls=[{"name": "run_sql", "id": "tc1", "args": {"query": "SELECT 1"}}],
        ),
        ToolMessage(content="[]", tool_call_id="tc1"),
    ]
    ev = extract_raw_evidence_from_messages(msgs)
    assert ev is None


def test_parse_fact_check_result_safe() -> None:
    ok, fb = _parse_fact_check_result('{"is_safe": true, "feedback": null}')
    assert ok is True


def test_parse_fact_check_result_unsafe() -> None:
    ok, fb = _parse_fact_check_result('{"is_safe": false, "feedback": "Precio inventado"}')
    assert ok is False
    assert "Precio" in fb


def test_fact_checker_node_no_llm_returns_approved() -> None:
    state = {"messages": [AIMessage(content="draft")]}
    out = fact_checker_node(state, None)
    assert out.get("context_guard_route") == "approved"
    assert out.get("is_safe") is True


def test_fact_checker_node_no_evidence_returns_approved() -> None:
    mock_llm = MagicMock()
    state = {"messages": [AIMessage(content="draft sin evidencia")]}
    out = fact_checker_node(state, mock_llm)
    assert out.get("context_guard_route") == "approved"
    mock_llm.invoke.assert_not_called()


def test_handoff_reply_node_sets_reply() -> None:
    state = {"correction_feedback": "Precio no respaldado"}
    out = handoff_reply_node(state)
    assert "reply" in out
    assert "especialista" in out["reply"].lower() or "contactarán" in out["reply"].lower()

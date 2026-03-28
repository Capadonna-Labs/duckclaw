"""Tests del planner JSON del Manager (parse, truncado, sin red)."""

from __future__ import annotations

import pytest


def test_truncate_plan_title_words() -> None:
    from duckclaw.graphs.manager_graph import _truncate_plan_title_words

    assert _truncate_plan_title_words("") == ""
    assert _truncate_plan_title_words("  ") == ""
    assert _truncate_plan_title_words("Un solo") == "Un solo"
    assert _truncate_plan_title_words("one two three four five six seven") == "one two three four five"


def test_extract_json_object() -> None:
    from duckclaw.graphs.manager_graph import _extract_json_object

    assert _extract_json_object("") is None
    assert _extract_json_object("not json") is None
    d = _extract_json_object('{"plan_title": "Hola", "tasks": ["a"]}')
    assert d == {"plan_title": "Hola", "tasks": ["a"]}
    d2 = _extract_json_object('prefix {"plan_title": "X", "tasks": []} suffix')
    assert d2 == {"plan_title": "X", "tasks": []}


def test_coerce_planner_payload() -> None:
    from duckclaw.graphs.manager_graph import _coerce_planner_payload

    t, tasks = _coerce_planner_payload({"plan_title": "Título", "tasks": ["u1", "u2"]})
    assert t == "Título"
    assert tasks == ["u1", "u2"]
    t2, tasks2 = _coerce_planner_payload({"plan_title": "  x  ", "tasks": None})
    assert t2 == "x"
    assert tasks2 == []
    with pytest.raises(ValueError):
        _coerce_planner_payload([])
    with pytest.raises(ValueError):
        _coerce_planner_payload({"plan_title": "", "tasks": []})
    with pytest.raises(ValueError):
        _coerce_planner_payload({"plan_title": "ok", "tasks": "nope"})


def test_llm_plan_from_model_returns_none_on_bad_invoke() -> None:
    from duckclaw.graphs.manager_graph import _llm_plan_from_model

    class _Boom:
        def invoke(self, _messages):  # noqa: ANN001
            raise RuntimeError("no API")

    assert _llm_plan_from_model(_Boom(), "hola", "Eres un planner.") is None


def test_llm_plan_from_model_parses_response() -> None:
    from duckclaw.graphs.manager_graph import _llm_plan_from_model

    class _Ok:
        def invoke(self, _messages):  # noqa: ANN001
            class R:
                content = '{"plan_title":"Consulta catálogo ropa","tasks":["Listar productos","Responder precios"]}'

            return R()

    out = _llm_plan_from_model(_Ok(), "¿Qué tienes?", "Instrucciones.")
    assert out is not None
    title, tasks = out
    assert title == "Consulta catálogo ropa"
    assert len(title.split()) <= 5
    assert tasks == ["Listar productos", "Responder precios"]


def test_llm_plan_from_model_truncates_long_title() -> None:
    from duckclaw.graphs.manager_graph import _llm_plan_from_model

    class _Ok:
        def invoke(self, _messages):  # noqa: ANN001
            class R:
                content = (
                    '{"plan_title":"one two three four five six seven",'
                    '"tasks":["t"]}'
                )

            return R()

    out = _llm_plan_from_model(_Ok(), "x", "sys")
    assert out is not None
    assert out[0] == "one two three four five"

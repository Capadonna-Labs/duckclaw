"""Normalización de historial para el API Gateway (Redis)."""

from __future__ import annotations

import sys
from pathlib import Path

_gw = Path(__file__).resolve().parent.parent / "services" / "api-gateway"
if str(_gw) not in sys.path:
    sys.path.insert(0, str(_gw))

from core.chat_history import normalize_history_item, normalize_history_list  # noqa: E402


def test_normalize_history_item_user_assistant() -> None:
    assert normalize_history_item({"role": "user", "content": "hola"}) == {"role": "user", "content": "hola"}
    assert normalize_history_item({"role": "assistant", "content": "x"}) == {"role": "assistant", "content": "x"}
    assert normalize_history_item({"role": "human", "content": "z"}) == {"role": "user", "content": "z"}


def test_normalize_history_item_rejects_system() -> None:
    assert normalize_history_item({"role": "system", "content": "nope"}) is None


def test_normalize_history_item_assistant_strips_telegram_escape() -> None:
    out = normalize_history_item({"role": "assistant", "content": r"hola\!"})
    assert out == {"role": "assistant", "content": "hola!"}


def test_normalize_history_list_filters() -> None:
    out = normalize_history_list(
        [
            {"role": "user", "content": "a"},
            {"role": "invalid", "content": "x"},
            {"role": "assistant", "content": "b"},
        ]
    )
    assert out == [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]

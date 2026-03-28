"""Colores de columna chat: alias e id distintos; usuarios distintos raramente iguales."""

from __future__ import annotations

import re

import pytest

from duckclaw.utils.logger import (
    format_chat_identity_column_for_terminal,
    format_chat_id_for_terminal,
)


@pytest.fixture
def colors_on(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("DUCKCLAW_LOG_NO_COLOR", raising=False)


def _ansi_codes(s: str) -> list[str]:
    return re.findall(r"\033\[[0-9;]+m", s)


def test_juan_and_aleila_not_same_palette_slot(colors_on, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    j = format_chat_identity_column_for_terminal("@Juan (1726618406)")
    a = format_chat_identity_column_for_terminal("@Aleila Camargo (8729050846)")
    assert j != a
    cj, ca = _ansi_codes(j), _ansi_codes(a)
    assert len(cj) >= 2 and len(ca) >= 2
    assert cj != ca


def test_alias_and_id_segments_use_different_codes(colors_on) -> None:
    s = format_chat_identity_column_for_terminal("@TestUser (999)")
    codes = _ansi_codes(s)
    assert len(set(codes)) >= 2


def test_format_chat_id_as_repr_wraps_colored_inner(colors_on) -> None:
    out = format_chat_id_for_terminal("@X (1)", as_repr=True)
    assert out.startswith("'")
    assert out.endswith("'")
    assert "\033[" in out


def test_no_color_plain_string(colors_on, monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert "\033" not in format_chat_identity_column_for_terminal("@A (1)")

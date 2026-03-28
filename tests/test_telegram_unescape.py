"""unescape_telegram_markdown_v2_layers evita acumulación de barras al re-escapar."""

from __future__ import annotations

from duckclaw.graphs.on_the_fly_commands import _telegram_safe, unescape_telegram_markdown_v2_layers


def test_unescape_one_layer_exclamation() -> None:
    assert unescape_telegram_markdown_v2_layers(r"hola\!") == "hola!"


def test_unescape_triple_before_exclamation_matches_double_escape_noise() -> None:
    # Simula salida ya escapada dos veces (modelo + gateway o historial + gateway).
    assert unescape_telegram_markdown_v2_layers(r"hola\\\!") == "hola!"


def test_telegram_safe_after_unescape_is_stable() -> None:
    raw = "¡Hola Valentina! Soy Leila."
    once = _telegram_safe(raw)
    twice = _telegram_safe(once)
    assert "\\" in twice
    healed = unescape_telegram_markdown_v2_layers(twice)
    assert healed == raw
    assert _telegram_safe(healed) == once


def test_roundtrip_plain() -> None:
    s = "Sin especiales raros"
    assert unescape_telegram_markdown_v2_layers(s) == s
    assert unescape_telegram_markdown_v2_layers(_telegram_safe(s)) == s

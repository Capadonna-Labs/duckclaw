"""Gateway: scrub de teléfonos no autorizados (LeilaAssistant)."""

from __future__ import annotations

import sys
from pathlib import Path

_gw = Path(__file__).resolve().parent.parent / "services" / "api-gateway"
if str(_gw) not in sys.path:
    sys.path.insert(0, str(_gw))

from core.leila_output_guard import (  # noqa: E402
    scrub_leila_contact_surface,
    scrub_leila_history_assistant_messages,
    scrub_leila_unauthorized_phones,
)


def test_scrub_replaces_placeholder_colombian_mobile() -> None:
    s = "Llame a la dueña al 300 123 4567 para el pedido."
    out = scrub_leila_unauthorized_phones(s)
    assert "300 123 4567" not in out
    assert "+57 3206929824" in out


def test_scrub_keeps_authorized_number() -> None:
    s = "Escríbanos a +57 3206929824"
    assert scrub_leila_unauthorized_phones(s) == s


def test_scrub_keeps_national_format() -> None:
    s = "Celular 320 692 9824"
    assert scrub_leila_unauthorized_phones(s) == s


def test_contact_surface_fixes_email_and_ig() -> None:
    s = "IG @leilastore_medellin mail contacto@leilastore.com tel 300 111 2233"
    out = scrub_leila_contact_surface(s)
    assert "@leilastore_medellin" not in out
    assert "@leilastore" in out
    assert "contacto@leilastore.com" not in out
    assert "aleilacamargo1069@gmail.com" in out
    assert "300 111 2233" not in out


def test_history_only_scrubs_assistant() -> None:
    items = [
        {"role": "user", "content": "mi mail es yo@cliente.com"},
        {"role": "assistant", "content": "Llame al 300 123 4567 o @leilastore_medellin"},
    ]
    out = scrub_leila_history_assistant_messages(items)
    assert "yo@cliente.com" in out[0]["content"]
    assert "300 123 4567" not in out[1]["content"]
    assert "@leilastore_medellin" not in out[1]["content"]

"""
Saneamiento determinista de salidas Leila (gateway): contacto inventado en texto.

Alineado con soul / CONTACTO OFICIAL. Teléfono, email e Instagram falsos se sustituyen
por los valores autorizados. Opcionalmente se aplica a mensajes ``assistant`` del
historial Redis para no reinyectar alucinaciones antiguas en el contexto del modelo.
"""

from __future__ import annotations

import os
import re


def _canonical_phone_digits() -> tuple[str, str]:
    """(dígitos internacionales 57..., últimos 10 nacionales)."""
    raw = (os.environ.get("DUCKCLAW_LEILA_PHONE_DIGITS") or "573206929824").strip()
    d = re.sub(r"\D", "", raw)
    if len(d) >= 10:
        return d, d[-10:]
    return "573206929824", "3206929824"


def _official_email() -> str:
    return (os.environ.get("DUCKCLAW_LEILA_OFFICIAL_EMAIL") or "aleilacamargo1069@gmail.com").strip().lower()


def _official_instagram_display() -> str:
    raw = (os.environ.get("DUCKCLAW_LEILA_OFFICIAL_INSTAGRAM") or "@leilastore").strip()
    return raw if raw.startswith("@") else f"@{raw.lstrip('@')}"


def _digits_allowed(d: str) -> bool:
    d = re.sub(r"\D", "", d)
    if not d:
        return False
    full, tail = _canonical_phone_digits()
    if d == full or d == tail:
        return True
    if len(d) == 12 and d.startswith("57") and d[2:] == tail:
        return True
    return False


# Móviles CO (3XX XXX XXXX) y variantes con +57 / 0057
_PHONE_RE = re.compile(
    r"(?:\+?57[\s\-]?|0057[\s\-]?)?3\d{2}[\s\-]?\d{3}[\s\-]?\d{4}\b|\+?573\d{9}\b",
    re.IGNORECASE,
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Variantes tipo @leilastore_medellin (soul solo autoriza @leilastore)
_IG_LEILA_SUFFIX_RE = re.compile(r"@leilastore_[a-z0-9_]+", re.IGNORECASE)


def scrub_leila_unauthorized_phones(text: str) -> str:
    """
    Cada coincidencia telefónica que no sea el número autorizado se reemplaza por
    el display oficial (``+57`` + espacio + 10 dígitos).
    """
    if not text or not isinstance(text, str):
        return text
    _, tail = _canonical_phone_digits()
    display = f"+57 {tail}" if len(tail) == 10 else "+57 3206929824"

    def _sub(m: re.Match[str]) -> str:
        if _digits_allowed(m.group(0)):
            return m.group(0)
        return display

    return _PHONE_RE.sub(_sub, text)


def scrub_leila_unauthorized_emails(text: str) -> str:
    """Sustituye cualquier email que no sea el oficial del soul."""
    if not text or not isinstance(text, str):
        return text
    official = _official_email()

    def _sub(m: re.Match[str]) -> str:
        if m.group(0).strip().lower() == official:
            return m.group(0)
        return official

    return _EMAIL_RE.sub(_sub, text)


def scrub_leila_instagram_variants(text: str) -> str:
    """Normaliza handles @leilastore_* al único autorizado."""
    if not text or not isinstance(text, str):
        return text
    ig = _official_instagram_display()
    return _IG_LEILA_SUFFIX_RE.sub(ig, text)


def scrub_leila_contact_surface(text: str) -> str:
    """Teléfono + email + Instagram (orden seguro para salida única)."""
    return scrub_leila_instagram_variants(
        scrub_leila_unauthorized_emails(scrub_leila_unauthorized_phones(text or ""))
    )


def scrub_leila_history_assistant_messages(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Copia la lista y aplica ``scrub_leila_contact_surface`` solo a rol ``assistant``.
    """
    out: list[dict[str, str]] = []
    for h in items:
        if not isinstance(h, dict):
            continue
        row = dict(h)
        role = str(row.get("role") or "").strip().lower()
        content = row.get("content")
        if role == "assistant" and isinstance(content, str):
            row["content"] = scrub_leila_contact_surface(content)
        elif "content" in row:
            row["content"] = str(content) if content is not None else ""
        out.append(row)
    return out


def is_leila_store_tenant(tenant_id: str | None) -> bool:
    return (tenant_id or "").strip() == "Leila Store"

"""Safe SQL helpers: identifier validation and value escaping.

Centralizes SQL safety patterns to prevent injection across the codebase.
DuckDB does not support parameterized queries through the C++ extension's
``execute``/``query`` API, so we rely on strict validation and escaping.
"""

from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def safe_identifier(name: str) -> str:
    """Validate and return a safe SQL identifier (table/column name).

    Raises ``ValueError`` if the name contains unsafe characters.
    """
    name = str(name).strip()
    if not name or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Identificador SQL inválido: {name!r}")
    return name


def is_safe_identifier(name: str) -> bool:
    """Return True if *name* is a valid SQL identifier."""
    return bool(name) and bool(_IDENTIFIER_RE.match(str(name).strip()))


def escape_value(value: str, max_len: int = 0) -> str:
    """Escape a string value for use in SQL single-quoted literals.

    Escapes single quotes by doubling them. Optionally truncates to *max_len*.
    """
    s = str(value).replace("'", "''")
    if max_len > 0:
        s = s[:max_len]
    return s


def escape_like(value: str) -> str:
    """Escape special LIKE metacharacters (``%`` and ``_``) in a value."""
    return str(value).replace("'", "''").replace("%", "\\%").replace("_", "\\_")


def validate_read_sql(sql: str) -> tuple[bool, str]:
    """Return (True, '') if *sql* is a safe read-only query, else (False, reason)."""
    sql = (sql or "").strip()
    if not sql:
        return False, "Query vacío."
    upper = sql.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH") or
            upper.startswith("SHOW") or upper.startswith("DESCRIBE")):
        return False, "Solo se permiten consultas SELECT, WITH, SHOW o DESCRIBE."
    _BLOCKED = re.compile(
        r"\b(DROP|TRUNCATE|ATTACH|DETACH|COPY|EXPORT|IMPORT|INSERT|UPDATE|DELETE|ALTER|CREATE)\b",
        re.IGNORECASE,
    )
    m = _BLOCKED.search(sql)
    if m:
        return False, f"No se permite {m.group(0).upper()} en consultas de lectura."
    return True, ""

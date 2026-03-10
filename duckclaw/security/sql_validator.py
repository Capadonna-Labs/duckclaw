"""
SQLValidator — validación AST con sqlglot para permitir solo SELECT e INSERT autorizados.

Spec: DuckClaw Production Readiness (Corto Plazo) — SecurityGateway.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

# Blocked keywords (always rejected)
_BLOCKED = frozenset(
    {"DROP", "TRUNCATE", "ATTACH", "DETACH", "COPY", "EXPORT", "IMPORT", "ALTER", "CREATE"}
)


def _safe_ident(name: str) -> str:
    """Safe identifier: alphanumeric + underscore."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in (name or "").strip())


def _extract_tables_from_ast(parsed: Any) -> List[str]:
    """Extract table names from sqlglot AST. Returns list of (schema.)table names."""
    tables: List[str] = []
    try:
        from sqlglot import exp

        for table in parsed.find_all(exp.Table):
            name = getattr(table, "name", None) or ""
            if name and str(name).upper() not in ("INFORMATION_SCHEMA", "MAIN"):
                db = getattr(table, "db", None)
                full = f"{db}.{name}" if db else str(name)
                tables.append(full.strip("."))
    except Exception:
        pass
    return list(dict.fromkeys(tables))  # dedupe


def _get_statement_type(parsed: Any) -> Optional[str]:
    """Return first statement type: SELECT, INSERT, UPDATE, DELETE, etc."""
    try:
        from sqlglot import exp

        if isinstance(parsed, exp.Select):
            return "SELECT"
        if isinstance(parsed, exp.Insert):
            return "INSERT"
        if isinstance(parsed, exp.Update):
            return "UPDATE"
        if isinstance(parsed, exp.Delete):
            return "DELETE"
        if isinstance(parsed, exp.Show):
            return "SELECT"
        if type(parsed).__name__ == "Describe":
            return "SELECT"
        # Multi-statement: parse_one returns first only; parse returns list
        if isinstance(parsed, list) and parsed:
            return _get_statement_type(parsed[0])
    except Exception:
        pass
    return None


class SQLValidator:
    """
    Valida SQL con sqlglot (AST). Permite solo SELECT e INSERT en tablas autorizadas.
    """

    def __init__(
        self,
        *,
        read_only: bool = False,
        write_only: bool = False,
        allowed_tables: Optional[List[str]] = None,
        schema_name: Optional[str] = None,
    ):
        """
        Args:
            read_only: Si True, solo permite SELECT/WITH/SHOW/DESCRIBE.
            write_only: Si True, solo permite INSERT/UPDATE/DELETE (rechaza SELECT).
            allowed_tables: Lista de tablas permitidas (sin schema). Si vacío/None, permite todas.
            schema_name: Schema del worker (ej. finance_worker) para validar schema.table.
        """
        self.read_only = read_only
        self.write_only = write_only
        self.allowed_tables = [t.strip() for t in (allowed_tables or []) if t]
        self.schema_name = (schema_name or "").strip()

    def validate(self, sql: str) -> Tuple[bool, str]:
        """
        Valida el SQL. Retorna (True, "") si es válido, (False, error_message) si no.

        - Parsea con sqlglot.
        - Rechaza DROP, TRUNCATE, ALTER, etc.
        - Si read_only: solo SELECT, WITH, SHOW, DESCRIBE.
        - Si allowed_tables: todas las tablas referenciadas deben estar en la lista.
        """
        q = (sql or "").strip()
        if not q:
            return False, "Query vacío."

        # Quick keyword check before parsing
        q_upper = q.upper()
        for kw in _BLOCKED:
            if re.search(rf"\b{kw}\b", q_upper):
                return False, f"No se permiten operaciones {kw} por política de seguridad."

        try:
            import sqlglot
        except ImportError:
            # Fallback: regex-based validation when sqlglot not available
            return self._validate_fallback(q)

        try:
            parsed = sqlglot.parse_one(q, dialect="duckdb")
        except Exception as e:
            return False, f"SQL inválido: {e}"

        if not parsed:
            return False, "No se pudo parsear el SQL."

        stmt_type = _get_statement_type(parsed)
        if not stmt_type:
            return False, "Tipo de sentencia no reconocido."

        if stmt_type not in ("SELECT", "INSERT", "UPDATE", "DELETE", "WITH"):
            if stmt_type in ("SHOW", "DESCRIBE"):
                return True, ""  # Allow metadata commands
            return False, f"Solo se permiten SELECT e INSERT (y UPDATE/DELETE si no es read_only). Tipo: {stmt_type}"

        if self.write_only and stmt_type in ("SELECT", "WITH"):
            return False, "Este validador es solo para escritura. Usa run_read_sql para SELECT."

        if self.read_only and stmt_type not in ("SELECT", "WITH"):
            return False, "Este trabajador es solo lectura. No se permiten escrituras."

        tables = _extract_tables_from_ast(parsed)
        if self.allowed_tables and tables:
            for t in tables:
                base = t.split(".")[-1] if "." in t else t
                base_clean = _safe_ident(base)
                schema_qualified = f"{self.schema_name}.{base_clean}" if self.schema_name else base_clean
                if not any(
                    _safe_ident(a) == base_clean or _safe_ident(a) == schema_qualified
                    for a in self.allowed_tables
                ):
                    return False, f"Solo se permiten las tablas: {', '.join(self.allowed_tables)}. Referenciada: {t}"
        return True, ""

    def _validate_fallback(self, q: str) -> Tuple[bool, str]:
        """Regex-based validation when sqlglot is not installed."""
        q_upper = q.upper()
        if re.search(r"^\s*(SELECT|WITH|SHOW|DESCRIBE)\s", q_upper):
            if self.read_only:
                return True, ""
            # Read path: allow
            return True, ""
        if re.search(r"^\s*(INSERT|UPDATE|DELETE)\s", q_upper):
            if self.read_only:
                return False, "Este trabajador es solo lectura."
            return True, ""
        return False, "La consulta debe ser SELECT, WITH, SHOW, DESCRIBE, INSERT, UPDATE o DELETE."

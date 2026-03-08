"""Bicameral memory architecture using unified DuckDB + PGQ."""

from __future__ import annotations

import json
import os
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import core

_READ_BLOCKED = re.compile(
    r"\b(DROP|ALTER|TRUNCATE|ATTACH|COPY|EXPORT|IMPORT|PRAGMA\s+table_info)\b",
    re.IGNORECASE,
)
_READ_ALLOWED = re.compile(r"^\s*(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\s", re.IGNORECASE)
_WRITE_ALLOWED = re.compile(r"^\s*(INSERT|UPDATE|DELETE)\s+", re.IGNORECASE)


def normalize_db_path(path: str, default_filename: str) -> str:
    """Normalize relative paths under db/ while keeping absolute and :memory:."""
    p = (path or "").strip()
    if not p:
        return f"db/{default_filename}"
    if p == ":memory:":
        return p
    if os.path.isabs(p):
        return p
    if p.startswith("db/"):
        return p
    return f"db/{p}"


def _ensure_parent(path: str) -> None:
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("'", "''")
    return f"'{text}'"


class SQLValidator:
    """Read-only SQL validator supporting SQL + PGQ read syntax."""

    def validate_read_sql(self, sql: str) -> tuple[bool, str]:
        s = (sql or "").strip()
        if not s:
            return False, "SQL vacío."
        if _READ_BLOCKED.search(s):
            return False, "Consulta bloqueada por seguridad."
        if not _READ_ALLOWED.search(s):
            return False, "La consulta debe ser de lectura (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN)."
        if ";" in s.rstrip(";"):
            return False, "Solo se permite una sentencia por consulta."
        return True, ""

    def validate_pgq_sql(self, sql: str) -> tuple[bool, str]:
        ok, err = self.validate_read_sql(sql)
        if not ok:
            return ok, err
        if "GRAPH_TABLE(" not in sql.upper():
            return False, "La consulta semántica debe usar GRAPH_TABLE(...)."
        return True, ""

    def validate_write_sql(self, sql: str) -> tuple[bool, str]:
        s = (sql or "").strip()
        if not s:
            return False, "SQL vacío."
        if not _WRITE_ALLOWED.search(s):
            return False, "Solo se permiten INSERT, UPDATE o DELETE."
        if ";" in s.rstrip(";"):
            return False, "Solo se permite una sentencia por ejecución."
        return True, ""


class OLAPEngine(ABC):
    """Interface for validated OLAP SQL execution."""

    @abstractmethod
    def execute_sql_validated(self, sql: str) -> dict[str, Any]:
        raise NotImplementedError


class SemanticEngine(ABC):
    """Interface for semantic relation retrieval."""

    @abstractmethod
    def execute_pgq_validated(self, sql: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def search_relations(self, user_query: str, limit: int = 8) -> dict[str, Any]:
        raise NotImplementedError


class DataMasker:
    """Mask potentially sensitive identifiers before LLM consumption."""

    SENSITIVE_KEYS = {"id", "user_id", "account_id", "from_account", "to_account", "source", "target"}

    def mask_text(self, text: str) -> str:
        t = str(text or "")
        # Simple redact for ids like user_12345 or acct-0987
        t = re.sub(r"\b([A-Za-z_]*id[A-Za-z_]*)([:=]\s*)([A-Za-z0-9_-]{3,})", r"\1\2***", t, flags=re.IGNORECASE)
        return t

    def mask_rows(self, payload: str) -> str:
        try:
            rows = json.loads(payload or "[]")
            if not isinstance(rows, list):
                return self.mask_text(payload)
            out: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                masked = {}
                for k, v in row.items():
                    if str(k).lower() in self.SENSITIVE_KEYS and v is not None:
                        masked[k] = "***"
                    else:
                        masked[k] = v
                out.append(masked)
            return json.dumps(out, ensure_ascii=False)
        except Exception:
            return self.mask_text(payload)


class DuckDBNativeEngine(OLAPEngine, SemanticEngine):
    """Unified SQL + PGQ engine over one DuckDB file."""

    def __init__(
        self,
        db: core.DuckClaw | None = None,
        db_path: str = "db/duckclaw.db",
        validator: SQLValidator | None = None,
        masker: DataMasker | None = None,
        graph_name: str = "financial_graph",
    ) -> None:
        self.db_path = normalize_db_path(db_path, "duckclaw.db")
        _ensure_parent(self.db_path)
        self.db = db or core.DuckClaw(self.db_path)
        self.validator = validator or SQLValidator()
        self.masker = masker or DataMasker()
        self.graph_name = graph_name
        self.pgq_enabled = False
        self._ensure_schema()
        self._ensure_property_graph()

    def _ensure_schema(self) -> None:
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                name TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS transfers (
                id TEXT PRIMARY KEY,
                from_account TEXT,
                to_account TEXT,
                amount DOUBLE,
                relation TEXT DEFAULT 'RELATED_TO',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def _ensure_property_graph(self) -> None:
        sql = f"""
        CREATE PROPERTY GRAPH {self.graph_name}
        VERTEX TABLES (
            accounts KEY (id)
        )
        EDGE TABLES (
            transfers SOURCE KEY (from_account) REFERENCES accounts(id)
                      DESTINATION KEY (to_account) REFERENCES accounts(id)
                      LABEL RELATED_TO
                      PROPERTIES (amount, relation)
        );
        """
        try:
            self.db.execute(sql)
            self.pgq_enabled = True
        except Exception:
            # PGQ may be unavailable in local DuckDB build; keep SQL fallback.
            self.pgq_enabled = False

    def execute_sql_validated(self, sql: str) -> dict[str, Any]:
        ok, err = self.validator.validate_read_sql(sql)
        if not ok:
            return {"source_id": "olap", "ok": False, "sql": sql, "error": err, "result": "[]"}
        try:
            result = self.db.query(sql)
            return {"source_id": "olap", "ok": True, "sql": sql, "error": "", "result": result}
        except Exception as e:  # pragma: no cover
            return {"source_id": "olap", "ok": False, "sql": sql, "error": str(e), "result": "[]"}

    def execute_pgq_validated(self, sql: str) -> dict[str, Any]:
        ok, err = self.validator.validate_pgq_sql(sql)
        if not ok:
            return {
                "source_id": "duckdb_pgq",
                "ok": False,
                "pgq_enabled": self.pgq_enabled,
                "sql": sql,
                "error": err,
                "result": "[]",
                "explain_analyze": "",
            }
        explain = ""
        try:
            explain = self.db.query(f"EXPLAIN ANALYZE {sql}")
        except Exception:
            explain = ""
        if not self.pgq_enabled:
            return {
                "source_id": "duckdb_pgq",
                "ok": False,
                "pgq_enabled": False,
                "sql": sql,
                "error": "PGQ no disponible en este runtime de DuckDB.",
                "result": "[]",
                "explain_analyze": explain,
            }
        try:
            result = self.db.query(sql)
            masked = self.masker.mask_rows(result)
            return {
                "source_id": "duckdb_pgq",
                "ok": True,
                "pgq_enabled": True,
                "sql": sql,
                "error": "",
                "result": masked,
                "explain_analyze": explain,
            }
        except Exception as e:
            return {
                "source_id": "duckdb_pgq",
                "ok": False,
                "pgq_enabled": self.pgq_enabled,
                "sql": sql,
                "error": str(e),
                "result": "[]",
                "explain_analyze": explain,
            }

    def _search_relations_sql_fallback(self, user_query: str, limit: int = 8) -> dict[str, Any]:
        q = (user_query or "").strip().lower()
        like = f"%{q.replace('%', '')}%"
        sql = (
            "SELECT from_account AS source, to_account AS target, relation, amount "
            "FROM transfers "
            f"WHERE lower(from_account) LIKE {_safe_sql_literal(like)} "
            f"OR lower(to_account) LIKE {_safe_sql_literal(like)} "
            f"OR lower(relation) LIKE {_safe_sql_literal(like)} "
            f"ORDER BY updated_at DESC LIMIT {int(limit)}"
        )
        out = self.execute_sql_validated(sql)
        return {
            "source_id": "duckdb_graph_fallback",
            "ok": out.get("ok", False),
            "pgq_enabled": self.pgq_enabled,
            "sql": sql,
            "error": out.get("error", ""),
            "result": self.masker.mask_rows(out.get("result", "[]")),
            "explain_analyze": "",
        }

    def search_relations(self, user_query: str, limit: int = 8) -> dict[str, Any]:
        sql = (
            f"SELECT * FROM GRAPH_TABLE({self.graph_name} "
            "MATCH (a:accounts)-[t:RELATED_TO]->(b:accounts) "
            f"COLUMNS (a.id AS source, b.id AS target, t.amount AS amount)) LIMIT {int(limit)}"
        )
        pgq = self.execute_pgq_validated(sql)
        if pgq.get("ok"):
            return pgq
        return self._search_relations_sql_fallback(user_query, limit=limit)

    def upsert_relations(self, relations: list[dict[str, Any]]) -> None:
        for rel in relations or []:
            src = str(rel.get("source") or "").strip()
            tgt = str(rel.get("target") or "").strip()
            if not src or not tgt:
                continue
            rtype = str(rel.get("relation") or "RELATED_TO").strip() or "RELATED_TO"
            amount = float(rel.get("amount") or 0.0)
            self.db.execute(
                f"INSERT OR IGNORE INTO accounts(id, name) VALUES ({_safe_sql_literal(src)}, {_safe_sql_literal(src)})"
            )
            self.db.execute(
                f"INSERT OR IGNORE INTO accounts(id, name) VALUES ({_safe_sql_literal(tgt)}, {_safe_sql_literal(tgt)})"
            )
            rel_id = str(rel.get("id") or f"{src}->{tgt}:{rtype}")
            self.db.execute(
                "INSERT OR REPLACE INTO transfers(id, from_account, to_account, amount, relation) VALUES ("
                f"{_safe_sql_literal(rel_id)},"
                f"{_safe_sql_literal(src)},"
                f"{_safe_sql_literal(tgt)},"
                f"{amount},"
                f"{_safe_sql_literal(rtype)}"
                ")"
            )
        # Keep trying to register graph definition; may become available later.
        self._ensure_property_graph()

    def execute_write(self, sql: str) -> tuple[bool, str]:
        ok, err = self.validator.validate_write_sql(sql)
        if not ok:
            return False, err
        try:
            self.db.execute(sql)
            return True, ""
        except Exception as e:
            return False, str(e)


class DuckDBOLAPEngine(OLAPEngine):
    """Compatibility OLAP wrapper over DuckDBNativeEngine."""

    def __init__(
        self,
        db: core.DuckClaw | None = None,
        db_path: str = "db/duckclaw.db",
        validator: SQLValidator | None = None,
    ) -> None:
        self.native = DuckDBNativeEngine(db=db, db_path=db_path, validator=validator)

    @property
    def db(self) -> core.DuckClaw:
        return self.native.db

    def execute_sql_validated(self, sql: str) -> dict[str, Any]:
        return self.native.execute_sql_validated(sql)

    # Backward compatibility for previous name.
    def execute_validated(self, sql: str) -> dict[str, Any]:
        return self.execute_sql_validated(sql)


@dataclass
class ContextualizedPrompt:
    """Unified context for downstream LLM calls."""

    prompt: str
    metadata: dict[str, Any]


class Synthesizer:
    """Merge OLAP + graph outputs into one LLM-ready prompt."""

    def synthesize(
        self,
        user_query: str,
        route: str,
        olap_result: dict[str, Any],
        semantic_result: dict[str, Any],
    ) -> ContextualizedPrompt:
        context = {
            "route": route,
            "source_ids": [olap_result.get("source_id"), semantic_result.get("source_id")],
            "olap": olap_result,
            "semantic": semantic_result,
        }
        text = (
            "### Bicameral Context\n"
            f"- user_query: {user_query}\n"
            f"- route: {route}\n"
            f"- source_ids: {context['source_ids']}\n"
            f"- olap_result: {json.dumps(olap_result, ensure_ascii=False)}\n"
            f"- semantic_result: {json.dumps(semantic_result, ensure_ascii=False)}\n"
        )
        return ContextualizedPrompt(prompt=text, metadata=context)


class _LangSmithTracer:
    """Best-effort LangSmith tracing with local fallback safety."""

    def __init__(self) -> None:
        self.enabled = (os.environ.get("DUCKCLAW_SEND_TO_LANGSMITH", "").strip().lower() == "true")
        self.project = os.environ.get("LANGCHAIN_PROJECT", "DuckClaw")
        self._client = None
        if self.enabled:
            try:
                from langsmith import Client

                self._client = Client()
            except Exception:
                self.enabled = False

    def start(self, name: str, inputs: dict[str, Any]) -> str | None:
        if not self.enabled or self._client is None:
            return None
        try:
            run = self._client.create_run(
                name=name,
                run_type="chain",
                inputs=inputs,
                project_name=self.project,
            )
            return str(getattr(run, "id", None) or run.get("id"))
        except Exception:
            return None

    def end(self, run_id: str | None, outputs: dict[str, Any], extra: dict[str, Any]) -> None:
        if not run_id or not self.enabled or self._client is None:
            return
        try:
            self._client.update_run(run_id, outputs=outputs, extra=extra, end_time=_utc_now())
        except Exception:
            pass


class BicameralNormalizer:
    """Normalize input payload into OLAP attrs and graph relations."""

    def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        rels: list[dict[str, Any]] = []
        for k, v in (payload or {}).items():
            if k == "relations" and isinstance(v, list):
                for rel in v:
                    if isinstance(rel, dict):
                        rels.append(rel)
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                attrs[k] = v
        if "entity" in attrs and "related_to" in attrs:
            rels.append(
                {
                    "source": str(attrs["entity"]),
                    "target": str(attrs["related_to"]),
                    "relation": "RELATED_TO",
                }
            )
        return {"attributes": attrs, "relations": rels}


class BicameralOrchestrator:
    """Route queries and execute SQL + PGQ in one DuckDB context."""

    def __init__(
        self,
        engine: DuckDBNativeEngine | None = None,
        synthesizer: Synthesizer | None = None,
        trace_path: str = "db/bicameral_traces.jsonl",
    ) -> None:
        self.engine = engine or DuckDBNativeEngine()
        self.synthesizer = synthesizer or Synthesizer()
        self.normalizer = BicameralNormalizer()
        self.trace_path = normalize_db_path(trace_path, "bicameral_traces.jsonl")
        _ensure_parent(self.trace_path)
        self.langsmith = _LangSmithTracer()

    def route_query(self, user_query: str) -> str:
        q = (user_query or "").lower()
        analytic_tokens = ("total", "sum", "promedio", "average", "count", "cuanto", "cuánto", "gasto", "ingreso")
        semantic_tokens = ("relacion", "relación", "conecta", "depende", "causa", "impacta", "vincula", "grafo")
        is_analytic = any(t in q for t in analytic_tokens)
        is_semantic = any(t in q for t in semantic_tokens)
        if is_analytic and is_semantic:
            return "hybrid"
        if is_analytic:
            return "olap"
        if is_semantic:
            return "graph"
        return "hybrid"

    def _build_olap_sql(self, user_query: str) -> str:
        q = (user_query or "").lower()
        if any(k in q for k in ("total", "suma", "sum", "gasto", "ingreso")):
            return "SELECT relation, SUM(amount) AS total FROM transfers GROUP BY relation ORDER BY total DESC"
        return (
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' ORDER BY table_name"
        )

    def _build_pgq_sql(self, user_query: str, limit: int = 8) -> str:
        _ = user_query
        return (
            f"SELECT * FROM GRAPH_TABLE({self.engine.graph_name} "
            "MATCH (a:accounts)-[t:RELATED_TO]->(b:accounts) "
            f"COLUMNS (a.id AS source, b.id AS target, t.amount AS amount)) LIMIT {int(limit)}"
        )

    def run_query(self, user_query: str, sql: str = "") -> ContextualizedPrompt:
        route = self.route_query(user_query)
        trace_id = str(uuid.uuid4())
        olap_sql = sql.strip() or self._build_olap_sql(user_query)
        pgq_sql = self._build_pgq_sql(user_query)
        ls_run_id = self.langsmith.start(
            "bicameral_orchestrator",
            {"user_query": user_query, "route": route, "olap_sql": olap_sql, "pgq_sql": pgq_sql},
        )

        olap_result = {"source_id": "olap", "ok": True, "sql": "", "error": "", "result": "[]"}
        semantic_result = {"source_id": "duckdb_pgq", "ok": True, "sql": "", "error": "", "result": "[]"}

        if route in ("olap", "hybrid"):
            olap_result = self.engine.execute_sql_validated(olap_sql)
        if route in ("graph", "hybrid"):
            semantic_result = self.engine.execute_pgq_validated(pgq_sql)
            if not semantic_result.get("ok"):
                semantic_result = self.engine.search_relations(user_query, limit=8)

        prompt = self.synthesizer.synthesize(user_query, route, olap_result, semantic_result)
        trace_payload = {
            "trace_id": trace_id,
            "timestamp": _utc_now(),
            "user_query": user_query,
            "route": route,
            "source_ids": prompt.metadata.get("source_ids", []),
            "olap_sql": olap_sql if route in ("olap", "hybrid") else "",
            "pgq_sql": pgq_sql if route in ("graph", "hybrid") else "",
            "pgq_explain_analyze": semantic_result.get("explain_analyze", ""),
            "olap_ok": bool(olap_result.get("ok")),
            "semantic_ok": bool(semantic_result.get("ok")),
        }
        self._append_trace(trace_payload)
        self.langsmith.end(
            ls_run_id,
            outputs={"contextualized_prompt": prompt.prompt},
            extra={
                "path": ["router", "duckdb_sql+pgq", "synthesizer"],
                "trace_id": trace_id,
                "pgq_explain_analyze": semantic_result.get("explain_analyze", ""),
            },
        )
        return prompt

    def ingest_critical_data(self, payload: dict[str, Any], insert_sql: str = "") -> dict[str, Any]:
        normalized = self.normalizer.normalize(payload or {})
        if insert_sql.strip():
            ok, err = self.engine.execute_write(insert_sql.strip())
            if not ok:
                return {"ok": False, "error": err, "normalized": normalized}
        self.engine.upsert_relations(normalized["relations"])
        self._append_trace(
            {
                "trace_id": str(uuid.uuid4()),
                "timestamp": _utc_now(),
                "event": "ingest_critical_data",
                "normalized": normalized,
                "source_ids": ["olap", "duckdb_pgq"],
            }
        )
        return {"ok": True, "normalized": normalized}

    def _append_trace(self, payload: dict[str, Any]) -> None:
        with Path(self.trace_path).open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

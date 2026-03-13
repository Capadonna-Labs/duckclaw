"""Load worker template assets: system_prompt.md, schema.sql, skills."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, List

from duckclaw.workers.manifest import WorkerSpec


def load_system_prompt(spec: WorkerSpec) -> str:
    """Load system_prompt.md from worker dir."""
    path = spec.worker_dir / "system_prompt.md"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return "Eres un asistente útil. Usa las herramientas disponibles cuando sea necesario."


def load_schema_sql(spec: WorkerSpec) -> str:
    """Load schema.sql from worker dir."""
    path = spec.worker_dir / "schema.sql"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def _ensure_agent_beliefs(db: Any, schema: str) -> None:
    """Create agent_beliefs table for homeostasis (Active Inference Framework)."""
    s = _safe_ident(schema)
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS {s}.agent_beliefs (
            belief_key VARCHAR PRIMARY KEY,
            target_value REAL NOT NULL,
            observed_value REAL,
            threshold REAL NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def run_schema(db: Any, spec: WorkerSpec) -> None:
    """Create isolated schema and run schema.sql."""
    schema = spec.schema_name
    # DuckDB: CREATE SCHEMA IF NOT EXISTS name;
    db.execute(f"CREATE SCHEMA IF NOT EXISTS {_safe_ident(schema)}")
    _ensure_agent_beliefs(db, schema)
    sql = load_schema_sql(spec)
    if not sql:
        return
    # Run each statement (split by ;)
    for stmt in _split_sql(sql):
        if stmt.strip():
            db.execute(stmt)


def _safe_ident(name: str) -> str:
    """Safe schema/table identifier (alphanumeric + underscore)."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name.strip())


def _split_sql(sql: str) -> List[str]:
    """Split SQL by semicolon, respecting strings."""
    out = []
    buf = []
    in_str = None
    i = 0
    while i < len(sql):
        c = sql[i]
        if in_str:
            if c == "\\" and i + 1 < len(sql):
                buf.append(sql[i : i + 2])
                i += 2
                continue
            if c == in_str:
                in_str = None
            buf.append(c)
            i += 1
            continue
        if c in ("'", '"'):
            in_str = c
            buf.append(c)
            i += 1
            continue
        if c == ";":
            out.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    if buf:
        out.append("".join(buf).strip())
    return out


def load_skills(spec: WorkerSpec, db: Any) -> List[Any]:
    """Load tools from skills/ directory. Each .py file can define get_tools(db, schema_name) -> list."""
    from langchain_core.tools import StructuredTool

    skills_dir = spec.worker_dir / "skills"
    tools: List[Any] = []
    if not skills_dir.is_dir():
        return tools

    schema = spec.schema_name
    for py_file in sorted(skills_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"duckclaw.workers.skill_{spec.worker_id}_{py_file.stem}"
        spec_loader = importlib.util.spec_from_file_location(module_name, py_file)
        if spec_loader is None:
            continue
        mod = importlib.util.module_from_spec(spec_loader)
        if spec_loader.loader is None:
            continue
        sys.modules[module_name] = mod
        try:
            spec_loader.loader.exec_module(mod)
        except Exception:
            continue
        if hasattr(mod, "get_tools"):
            try:
                skill_tools = mod.get_tools(db, schema, spec)
            except TypeError:
                skill_tools = mod.get_tools(db, schema)
            if isinstance(skill_tools, list):
                tools.extend(skill_tools)
            elif isinstance(skill_tools, StructuredTool):
                tools.append(skill_tools)
        elif hasattr(mod, "tools") and isinstance(getattr(mod, "tools"), list):
            tools.extend(getattr(mod, "tools"))

    return tools

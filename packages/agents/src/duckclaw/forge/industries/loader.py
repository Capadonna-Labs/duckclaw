"""Carga schema.sql y seed_data.sql de plantillas bajo forge/templates/industries/."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from duckclaw.workers.loader import _split_sql

_log = logging.getLogger(__name__)

# Evita import circular con duckclaw.forge.__init__
_FORGE_DIR = Path(__file__).resolve().parent.parent
INDUSTRIES_DIR = _FORGE_DIR / "templates" / "industries"


def resolve_industry_dir(template_id: str) -> Path:
    tid = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in (template_id or "").strip())[:128]
    if not tid:
        raise ValueError("template_id vacío o inválido")
    d = INDUSTRIES_DIR / tid
    if not d.is_dir():
        raise FileNotFoundError(f"Plantilla industry no encontrada: {d}")
    return d


def list_industry_templates() -> list[str]:
    if not INDUSTRIES_DIR.is_dir():
        return []
    return sorted(p.name for p in INDUSTRIES_DIR.iterdir() if p.is_dir() and (p / "schema.sql").is_file())


def load_industry_manifest(template_id: str) -> dict[str, Any]:
    d = resolve_industry_dir(template_id)
    mf = d / "manifest.yaml"
    if not mf.is_file():
        return {"id": template_id}
    data = yaml.safe_load(mf.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {"id": template_id}


def _executable_statements(sql: str) -> list[str]:
    out: list[str] = []
    for s in _split_sql(sql):
        s = s.strip()
        if not s:
            continue
        has_code = False
        for line in s.splitlines():
            t = line.strip()
            if t and not t.startswith("--"):
                has_code = True
                break
        if has_code:
            out.append(s)
    return out


def apply_industry_to_db(db: Any, industry_id: str, *, run_seed: bool = True) -> None:
    """
    Ejecuta schema.sql y opcionalmente seed_data.sql de la plantilla.
    Fallos en extensiones opcionales (INSTALL) se registran y se reintenta el resto donde aplique.
    """
    d = resolve_industry_dir(industry_id)
    schema_path = d / "schema.sql"
    if not schema_path.is_file():
        raise FileNotFoundError(f"Falta schema.sql en {d}")

    sql = schema_path.read_text(encoding="utf-8")
    statements = _executable_statements(sql)

    for stmt in statements:
        try:
            db.execute(stmt)
        except Exception as e:
            st_upper = stmt.upper().strip()
            if st_upper.startswith("INSTALL ") or st_upper.startswith("LOAD "):
                _log.warning("Industry schema: extensión omitida o fallida (%s): %s", stmt[:80], e)
                continue
            if "HNSW" in st_upper or "USING HNSW" in st_upper:
                _log.warning("Industry schema: índice VSS omitido: %s", e)
                continue
            if "PROPERTY GRAPH" in st_upper or "DROP PROPERTY GRAPH" in st_upper:
                _log.warning("Industry schema: property graph omitido: %s", e)
                continue
            raise

    if run_seed:
        seed_path = d / "seed_data.sql"
        if seed_path.is_file():
            seed_sql = seed_path.read_text(encoding="utf-8")
            for stmt in _executable_statements(seed_sql):
                try:
                    db.execute(stmt)
                except Exception as e:
                    _log.warning("Industry seed: sentencia fallida (%s): %s", stmt[:120], e)

    try:
        seed_industry_agent_config(db, industry_id)
    except Exception as e:
        _log.warning("seed_industry_agent_config: %s", e)


def seed_industry_agent_config(db: Any, industry_id: str) -> None:
    """Registra claves en main.agent_config (spec §5.4)."""
    manifest = load_industry_manifest(industry_id)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_config (
            key VARCHAR PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    def upsert(k: str, v: str) -> None:
        kk = (k or "")[:128]
        vv = (v or "")[:16384]
        db.execute(
            """
            INSERT INTO main.agent_config (key, value) VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET
                value = excluded.value,
                updated_at = now()
            """,
            [kk, vv],
        )

    upsert("industry_template", industry_id)
    defaults = manifest.get("agent_config_defaults") or {}
    for k, v in defaults.items():
        if isinstance(v, bool):
            upsert(str(k), "true" if v else "false")
        else:
            upsert(str(k), str(v))
    workers = manifest.get("default_workers") or []
    if workers:
        import json

        upsert("industry_default_workers", json.dumps(workers))

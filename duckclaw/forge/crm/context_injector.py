"""
GraphContextInjector — Read pipeline: consulta PGQ y formatea perfil 360 para el prompt.

Spec: specs/Sovereign_CRM_Memoria_Bicameral_DuckDB_PGQ.md
"""

from __future__ import annotations

import json
from typing import Any, Optional

from duckclaw.forge.crm.schema import ensure_crm_graph_schema, _crm_pgq_available


def graph_context_injector(
    db: Any,
    lead_id: Optional[str] = None,
) -> str:
    """
    Consulta el grafo powerseal_crm para el perfil 360 del lead.
    Retorna bloque Markdown para inyectar en <lead_context>...</lead_context>.
    """
    if not lead_id or not str(lead_id).strip():
        return ""
    if not ensure_crm_graph_schema(db) or not _crm_pgq_available(db):
        return ""

    lead_ref = str(lead_id).strip().replace("'", "''")[:128]

    try:
        # Consulta relacional (compatible con/sin PGQ): aristas salientes del Lead
        sql = f"""
        SELECT e.relationship, e.properties AS edge_props, n2.node_id AS target_id, n2.label AS target_label, n2.properties AS target_props
        FROM memory_edges e
        JOIN memory_nodes n1 ON e.source_id = n1.node_id
        JOIN memory_nodes n2 ON e.target_id = n2.node_id
        WHERE n1.node_id = '{lead_ref}' AND n1.label = 'Lead'
          AND e.relationship IN ('WORKS_AT', 'INTERESTED_IN', 'PURCHASED')
        LIMIT 20
        """
        raw = db.query(sql)
        rows = raw if isinstance(raw, list) else (json.loads(raw) if isinstance(raw, str) else [])
    except Exception:
        return ""

    if not rows or not isinstance(rows, list):
        return ""

    lines = ["**Perfil del cliente (CRM):**"]
    seen = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        rel = r.get("relationship") or "?"
        tgt = r.get("target_id") or "?"
        props = r.get("target_props") or r.get("edge_props")
        key = f"{rel}:{tgt}"
        if key in seen:
            continue
        seen.add(key)
        name = ""
        if props:
            try:
                p = json.loads(props) if isinstance(props, str) else props
                name = p.get("name") or p.get("sku") or p.get("sector") or ""
            except Exception:
                pass
        label = f" ({name})" if name else ""
        lines.append(f"- {rel}: {tgt}{label}")
        if len(lines) >= 15:
            break

    if len(lines) <= 1:
        return ""
    return "\n".join(lines)

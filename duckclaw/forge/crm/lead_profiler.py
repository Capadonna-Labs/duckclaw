"""
GraphLeadProfiler — Write pipeline: extrae tripletas comerciales del chat y persiste en PGQ.

Spec: specs/Sovereign_CRM_Memoria_Bicameral_DuckDB_PGQ.md
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from duckclaw.forge.crm.schema import (
    CRM_NODE_LABELS,
    CRM_RELATIONSHIPS,
    ensure_crm_graph_schema,
    _crm_pgq_available,
)


def _normalize_lead_id(phone: str) -> str:
    """Normaliza teléfono o ID a formato estable."""
    s = (phone or "").strip()
    digits = re.sub(r"\D", "", s)
    if digits:
        return f"+{digits}" if not s.startswith("+") else f"+{digits}"
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", s)[:64] or "unknown"


def _safe_esc(s: str) -> str:
    return str(s or "").replace("'", "''")[:256]


def graph_lead_profiler(
    db: Any,
    llm: Any,
    chat_history: list[dict],
    lead_id: Optional[str] = None,
) -> int:
    """
    Extrae tripletas del historial, valida ontología CRM e inserta/actualiza memory_nodes y memory_edges.
    Retorna número de tripletas insertadas.
    """
    if not chat_history and not lead_id:
        return 0
    if not ensure_crm_graph_schema(db) or not _crm_pgq_available(db):
        return 0
    if llm is None:
        return 0

    # Construir texto del chat
    lines = []
    for h in (chat_history or [])[-10:]:  # Últimas 10 interacciones
        role = (h.get("role") or "").lower()
        content = (h.get("content") or "").strip()
        if role == "user":
            lines.append(f"Usuario: {content}")
        elif role == "assistant":
            lines.append(f"Asistente: {content}")
    chat_text = "\n".join(lines)[:4000]
    if not chat_text.strip():
        return 0

    prompt = f"""Analiza este historial de chat comercial B2B y extrae tripletas de conocimiento.

Ontología:
- Nodos: Lead (cliente, identificado por teléfono), Company (empresa), Product (producto/SKU)
- Relaciones: WORKS_AT (Lead trabaja en Company), INTERESTED_IN (Lead interesado en Product), PURCHASED (Lead compró Product)

Formato de salida (una tripleta por línea):
phone_or_lead_id | RELATIONSHIP | target_value

Ejemplo: +573231234567 | WORKS_AT | EPM
Ejemplo: +573231234567 | INTERESTED_IN | 3121AI

Si el usuario menciona urgencia ("urgente", "asap", "lo antes posible"), incluye la tripleta con INTERESTED_IN.
Si no hay tripletas claras, responde solo: NINGUNA

Chat:
{chat_text}
"""
    try:
        resp = llm.invoke(prompt)
        reply = (getattr(resp, "content", None) or str(resp) or "").strip()
    except Exception:
        return 0

    if "NINGUNA" in reply.upper() or not reply:
        return 0

    inserted = 0
    for line in reply.splitlines():
        line = line.strip()
        if "|" not in line or len(line) < 5:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        source_raw, predicate, target = parts[0], parts[1].upper(), parts[2]
        if predicate not in CRM_RELATIONSHIPS:
            continue

        source_id = _normalize_lead_id(source_raw) if source_raw else (lead_id or "session")
        if not source_id:
            source_id = _normalize_lead_id("session")
        target_id = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", (target or "").strip())[:64] or "unknown"

        # Inferir labels
        if predicate == "WORKS_AT":
            sub_label, obj_label = "Lead", "Company"
        elif predicate in ("INTERESTED_IN", "PURCHASED"):
            sub_label, obj_label = "Lead", "Product"
        else:
            sub_label, obj_label = "Lead", "Company"

        sub_props = json.dumps({"phone": source_id, "name": source_raw or source_id})
        obj_props = json.dumps(
            {"name": target, "sector": target} if obj_label == "Company" else {"sku": target, "category": target}
        )
        edge_props = "null"
        if predicate == "INTERESTED_IN":
            edge_props = json.dumps({
                "intent_level": "high" if any(u in chat_text.lower() for u in ("urgente", "asap", "rápido")) else "medium",
                "last_inquiry": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })
        elif predicate == "PURCHASED":
            edge_props = json.dumps({
                "quantity": 1,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })

        sub_esc = _safe_esc(source_id)
        obj_esc = _safe_esc(target_id)
        sub_props_esc = _safe_esc(sub_props)
        obj_props_esc = _safe_esc(obj_props)
        edge_props_esc = _safe_esc(edge_props) if edge_props != "null" else "null"

        try:
            db.execute(f"""
                INSERT INTO memory_nodes (node_id, label, properties) VALUES ('{sub_esc}', '{sub_label}', '{sub_props_esc}')
                ON CONFLICT (node_id) DO UPDATE SET label = EXCLUDED.label, properties = EXCLUDED.properties
            """)
            db.execute(f"""
                INSERT INTO memory_nodes (node_id, label, properties) VALUES ('{obj_esc}', '{obj_label}', '{obj_props_esc}')
                ON CONFLICT (node_id) DO UPDATE SET label = EXCLUDED.label, properties = EXCLUDED.properties
            """)
            eid = f"{sub_esc}_{predicate}_{obj_esc}"[:128].replace("'", "''")
            props_col = ", properties" if edge_props != "null" else ""
            props_val = f", '{edge_props_esc}'" if edge_props != "null" else ""
            db.execute(f"""
                INSERT INTO memory_edges (edge_id, source_id, target_id, relationship, weight{props_col})
                VALUES ('{eid}', '{sub_esc}', '{obj_esc}', '{predicate}', 1.0{props_val})
                ON CONFLICT (edge_id) DO UPDATE SET weight = memory_edges.weight + 0.1
            """)
            inserted += 1
        except Exception:
            continue

    # Actualizar lead_score si hay INTERESTED_IN con urgencia
    if inserted > 0 and lead_id:
        try:
            lid = _safe_esc(_normalize_lead_id(lead_id))
            db.execute(f"""
                UPDATE memory_nodes SET properties = json_merge_patch(COALESCE(properties, '{{}}'), '{{"lead_score": 85}}')
                WHERE node_id = '{lid}' AND label = 'Lead'
            """)
        except Exception:
            pass

    return inserted


def record_learned_workaround(
    db: Any,
    agent_id: str,
    api_name: str,
    error_pattern: str,
    fix: str,
) -> bool:
    """
    Registra un patrón LEARNED_WORKAROUND en PGQ reutilizando memory_nodes y memory_edges.

    Modelo lógico (sin crear tablas nuevas):
    - Nodo origen: (Agent {id: agent_id})
    - Nodo destino: (API {name: api_name})
    - Arista: [:LEARNED_WORKAROUND {error_pattern: ..., fix: ...}]
    """
    if not ensure_crm_graph_schema(db):
        return False
    if not _crm_pgq_available(db):
        # Aunque PGQ no esté cargado, seguimos usando las tablas relacionales;
        # otro proceso puede recrear el grafo property desde ellas.
        pass

    agent_id = (agent_id or "").strip() or "unknown_agent"
    api_name = (api_name or "").strip() or "unknown_api"
    error_pattern = (error_pattern or "").strip()
    fix = (fix or "").strip()
    if not error_pattern or not fix:
        return False

    agent_node_id = _safe_esc(agent_id)
    api_node_id = _safe_esc(api_name)
    agent_props = _safe_esc(json.dumps({"id": agent_id}))
    api_props = _safe_esc(json.dumps({"name": api_name}))
    edge_id = f"{agent_node_id}_LEARNED_WORKAROUND_{api_node_id}"[:128].replace("'", "''")
    edge_props = _safe_esc(json.dumps({"error_pattern": error_pattern, "fix": fix}))

    try:
        db.execute(
            f"""
            INSERT INTO memory_nodes (node_id, label, properties)
            VALUES ('{agent_node_id}', 'Agent', '{agent_props}')
            ON CONFLICT (node_id) DO UPDATE
            SET label = EXCLUDED.label, properties = EXCLUDED.properties
            """
        )
        db.execute(
            f"""
            INSERT INTO memory_nodes (node_id, label, properties)
            VALUES ('{api_node_id}', 'API', '{api_props}')
            ON CONFLICT (node_id) DO UPDATE
            SET label = EXCLUDED.label, properties = EXCLUDED.properties
            """
        )
        db.execute(
            f"""
            INSERT INTO memory_edges (edge_id, source_id, target_id, relationship, weight, properties)
            VALUES ('{edge_id}', '{agent_node_id}', '{api_node_id}', 'LEARNED_WORKAROUND', 1.0, '{edge_props}')
            ON CONFLICT (edge_id) DO UPDATE
            SET properties = EXCLUDED.properties, weight = memory_edges.weight + 0.1
            """
        )
        return True
    except Exception:
        return False

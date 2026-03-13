# specs/Estructura_Basada_en_Grafos_DuckDB_PGQ_GraphRAG.md

"""Memoria estructural basada en grafos (DuckDB PGQ / GraphRAG).

- Schema: memory_nodes, memory_edges, property graph duckclaw_kg (duckpgq).
- GraphMemoryExtractor: extrae tripletas (S,P,O) de la última interacción y persiste en el grafo.
- GraphContextRetriever: consulta PGQ por entidades del mensaje e inyecta contexto en el prompt.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

# Ontología permitida (spec: financiera)
ALLOWED_NODE_LABELS = frozenset({"USER", "MERCHANT", "CATEGORY", "PREFERENCE", "PLACE", "PRODUCT"})
ALLOWED_RELATIONSHIPS = frozenset({"SPENDS_ON", "PREFERS", "LOCATED_IN", "BELONGS_TO", "BOUGHT"})

_GRAPH_AVAILABLE: bool | None = None


def _graph_rag_available(db: Any) -> bool:
    global _GRAPH_AVAILABLE
    if _GRAPH_AVAILABLE is not None:
        return _GRAPH_AVAILABLE
    try:
        db.execute("INSTALL duckpgq FROM community;")
        db.execute("LOAD duckpgq;")
        _GRAPH_AVAILABLE = True
    except Exception:
        _GRAPH_AVAILABLE = False
    return _GRAPH_AVAILABLE


def ensure_graph_rag_schema(db: Any) -> bool:
    """Crea tablas memory_nodes, memory_edges y el property graph duckclaw_kg. Devuelve True si PGQ está disponible."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS memory_nodes (
            node_id VARCHAR PRIMARY KEY,
            label VARCHAR,
            properties JSON
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS memory_edges (
            edge_id VARCHAR PRIMARY KEY,
            source_id VARCHAR,
            target_id VARCHAR,
            relationship VARCHAR,
            weight DOUBLE DEFAULT 1.0,
            FOREIGN KEY (source_id) REFERENCES memory_nodes(node_id),
            FOREIGN KEY (target_id) REFERENCES memory_nodes(node_id)
        )
    """)
    if not _graph_rag_available(db):
        return False
    try:
        db.execute("DROP PROPERTY GRAPH IF EXISTS duckclaw_kg;")
        db.execute("""
            CREATE PROPERTY GRAPH duckclaw_kg
            VERTEX TABLES (memory_nodes LABEL entity)
            EDGE TABLES (
                memory_edges SOURCE KEY (source_id) REFERENCES memory_nodes (node_id)
                             DESTINATION KEY (target_id) REFERENCES memory_nodes (node_id)
                             LABEL relation
            )
        """)
    except Exception:
        return False
    return True


def _normalize_id(name: str, label: str) -> str:
    """Identificador estable para nodos: label:name normalizado."""
    safe = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", (name or "").strip())[:128]
    return f"{label}:{safe}" if safe else f"{label}:{uuid.uuid4().hex[:8]}"


def _validate_triplet(subject: str, subject_label: str, predicate: str, obj: str, object_label: str) -> bool:
    if not subject or not obj or not predicate:
        return False
    return (
        subject_label in ALLOWED_NODE_LABELS
        and object_label in ALLOWED_NODE_LABELS
        and predicate in ALLOWED_RELATIONSHIPS
    )


def graph_memory_extractor(db: Any, llm: Any, user_content: str, assistant_content: str) -> None:
    """Write pipeline: extrae tripletas (S,P,O) del diálogo, valida ontología e inserta/actualiza memory_nodes y memory_edges.
    Pensado para ejecutarse en background (no bloquear TTFT).
    """
    if not user_content and not assistant_content:
        return
    if not _graph_rag_available(db):
        return
    try:
        prompt = """Extrae de este diálogo todas las tripletas de conocimiento en formato:
Sujeto | EtiquetaSujeto | Predicado | Objeto | EtiquetaObjeto
Etiquetas de nodo permitidas: USER, MERCHANT, CATEGORY, PREFERENCE, PLACE, PRODUCT.
Predicados permitidos: SPENDS_ON, PREFERS, LOCATED_IN, BELONGS_TO, BOUGHT.
Una tripleta por línea. Si no hay tripletas claras, responde solo: NINGUNA

Usuario: """
        prompt += (user_content or "")[:2000] + "\n\nAsistente: " + (assistant_content or "")[:2000]
        resp = llm.invoke(prompt)
        reply_text = (getattr(resp, "content", None) or str(resp) or "").strip()
        lines = [ln.strip() for ln in reply_text.splitlines() if "|" in ln and "NINGUNA" not in ln]
        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 5:
                continue
            subject, sub_label, predicate, obj, obj_label = parts[0], parts[1], parts[2], parts[3], parts[4]
            if not _validate_triplet(subject, sub_label, predicate, obj, obj_label):
                continue
            sid = _normalize_id(subject, sub_label)
            oid = _normalize_id(obj, obj_label)
            sub_props = json.dumps({"name": subject})
            obj_props = json.dumps({"name": obj})
            sub_esc = sid.replace("'", "''")
            sub_props_esc = sub_props.replace("'", "''")
            obj_esc = oid.replace("'", "''")
            obj_props_esc = obj_props.replace("'", "''")
            db.execute(
                f"""
                INSERT INTO memory_nodes (node_id, label, properties) VALUES ('{sub_esc}', '{sub_label}', '{sub_props_esc}')
                ON CONFLICT (node_id) DO UPDATE SET label = EXCLUDED.label, properties = EXCLUDED.properties
                """
            )
            db.execute(
                f"""
                INSERT INTO memory_nodes (node_id, label, properties) VALUES ('{obj_esc}', '{obj_label}', '{obj_props_esc}')
                ON CONFLICT (node_id) DO UPDATE SET label = EXCLUDED.label, properties = EXCLUDED.properties
                """
            )
            eid = f"{sid}_{predicate}_{oid}"[:128].replace("'", "''")
            db.execute(
                f"""
                INSERT INTO memory_edges (edge_id, source_id, target_id, relationship, weight)
                VALUES ('{eid}', '{sub_esc}', '{obj_esc}', '{predicate}', 1.0)
                ON CONFLICT (edge_id) DO UPDATE SET weight = memory_edges.weight + 0.1
                """
            )
    except Exception:
        pass


def _extract_entity_candidates(text: str) -> list[str]:
    """Extrae candidatos a entidades: palabras entre comillas y palabras en mayúscula o sustantivos cortos."""
    candidates = []
    for m in re.finditer(r'"([^"]+)"', text):
        candidates.append(m.group(1).strip())
    for m in re.finditer(r"\b([A-Z][a-záéíóúñ]+(?:\s+[A-Z][a-záéíóúñ]+)*)\b", text):
        candidates.append(m.group(1).strip())
    words = re.findall(r"\b\w{3,20}\b", text.lower())
    for w in words:
        if w not in {"que", "los", "las", "una", "uno", "por", "para", "con", "del", "como", "donde"}:
            candidates.append(w)
    return list(dict.fromkeys(candidates))[:15]


def graph_context_retriever(db: Any, incoming: str, chat_id: Any = None) -> str:
    """Read pipeline: entidades del mensaje, consulta PGQ (MATCH) y devuelve bloque de contexto para el system prompt."""
    if not _graph_rag_available(db):
        return ""
    entities = _extract_entity_candidates(incoming or "")
    if not entities:
        return ""
    try:
        # Traer aristas del grafo; DuckPGQ puede devolver columnas con sufijos (_1, _2) para duplicados
        sql = """
        SELECT * FROM GRAPH_TABLE(duckclaw_kg
            MATCH (s:entity)-[r:relation]->(t:entity)
            COLUMNS (s.node_id, s.label, s.properties, r.relationship, t.node_id, t.label, t.properties)
        )
        LIMIT 50
        """
        raw = db.query(sql)
        rows = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, list) else [])
        if not rows or not isinstance(rows, list):
            return ""
        entity_set = {e.lower() for e in entities}
        lines = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            src_id = r.get("node_id") or r.get("source_id") or "?"
            rel = r.get("relationship") or "?"
            tgt_id = r.get("node_id_1") or r.get("target_id") or "?"
            sp, tp = r.get("properties"), r.get("properties_1")
            src_name = (json.loads(sp).get("name", "") if isinstance(sp, str) else (sp.get("name", "") if isinstance(sp, dict) else "")) or ""
            tgt_name = (json.loads(tp).get("name", "") if isinstance(tp, str) else (tp.get("name", "") if isinstance(tp, dict) else "")) or ""
            if entity_set and not any(ent in (src_name or src_id).lower() or ent in (tgt_name or tgt_id).lower() for ent in entity_set):
                continue
            lines.append(f"  - {src_id} --[{rel}]--> {tgt_id}")
            if len(lines) >= 20:
                break
        return "Contexto estructural (grafo de conocimiento):\n" + "\n".join(lines) if lines else ""
    except Exception:
        return ""


def run_graph_memory_extractor_background(db: Any, llm: Any, user_content: str, assistant_content: str) -> None:
    """Ejecuta GraphMemoryExtractor en background (thread o asyncio) para no bloquear."""
    import threading
    t = threading.Thread(target=graph_memory_extractor, args=(db, llm, user_content, assistant_content))
    t.daemon = True
    t.start()

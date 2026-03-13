# Layer 1: Memoria Analítica y Arquitectura de Datos

Consolidación de persistencia, búsqueda semántica (RAG), grafos (PGQ) y transferencia de datos de alto rendimiento (Arrow). Incluye: motores híbridos, GraphRAG, Vector RAG, pipeline Zero-Copy, estrategia de persistencia, CRM bicameral y derecho al olvido.

---

## 1. Motores de Persistencia Híbrida

| Tipo de Dato | Motor | Uso |
|:---|:---|:---|
| **Relacional (OLAP)** | DuckDB | Datos financieros, transacciones, agregaciones. |
| **Estado efímero** | Redis | Cola de escritura (`duckdb_write_queue`), locks, estado de sesión. |
| **Vectorial (RAG)** | DuckDB + VSS | Embeddings locales, búsqueda por similitud. |
| **Grafos (semántico)** | DuckDB PGQ | Relaciones multi-salto sobre `memory_nodes` / `memory_edges`. |

**Singleton Writer Bridge**: Todas las escrituras a DuckDB pasan por una cola única (Redis → DB-Writer) para evitar accesos concurrentes. Shared-Nothing Analytics: workers pueden tener DuckDB local y consolidar vía Parquet al Datalake.

---

## 2. Memoria Estructural (DuckDB PGQ / GraphRAG)

Grafo de propiedades sobre tablas relacionales estándar (sin motor de grafos externo).

### DDL base

```sql
CREATE TABLE memory_nodes (
    node_id VARCHAR PRIMARY KEY,
    label VARCHAR,
    properties JSON
);

CREATE TABLE memory_edges (
    edge_id VARCHAR PRIMARY KEY,
    source_id VARCHAR,
    target_id VARCHAR,
    relationship VARCHAR,
    weight DOUBLE DEFAULT 1.0,
    FOREIGN KEY (source_id) REFERENCES memory_nodes(node_id),
    FOREIGN KEY (target_id) REFERENCES memory_nodes(node_id)
);

INSTALL pgq; LOAD pgq;
CREATE OR REPLACE PROPERTY GRAPH duckclaw_kg
VERTEX TABLES (memory_nodes LABEL entity)
EDGE TABLES (
    memory_edges SOURCE KEY (source_id) REFERENCES memory_nodes (node_id)
                 DESTINATION KEY (target_id) REFERENCES memory_nodes (node_id)
                 LABEL relation
);
```

### Skills de grafo

- **GraphMemoryExtractor** (write): Post-respuesta, extrae tripletas (Sujeto, Predicado, Objeto) con LLM, valida ontología, `INSERT ON CONFLICT DO UPDATE` en `memory_nodes`/`memory_edges`.
- **GraphContextRetriever** (read): Antes del LLM, pattern matching con `GRAPH_TABLE`/PGQ; resultado como bloque de contexto en el prompt.
- **Learned Workarounds (PGQ)**: Sin tablas nuevas. Patrón `(Agent)-[:LEARNED_WORKAROUND {error_pattern, fix}]->(API)` en `memory_edges`; nodos Agent y API en `memory_nodes`. GraphLeadProfiler registra correcciones de APIs.

### CRM / grafo comercial (Bicameral)

Ontología B2B sobre las mismas tablas: nodos Lead, Company, Product; aristas `WORKS_AT`, `INTERESTED_IN`, `PURCHASED`. **GraphLeadProfiler** extrae tripletas del chat y hace upsert; **GraphContextInjector** inyecta perfil 360 (PGQ) en el prompt. Derecho al olvido: borrar nodo Lead elimina aristas en cascada.

---

## 3. Vector RAG (DuckDB VSS)

Búsqueda semántica local sin Pinecone/Qdrant.

- **Esquema**: tabla con `embedding FLOAT[768]`, índice HNSW (métrica cosine).
- **CatalogRetriever**: vectorizar query → `ORDER BY array_cosine_distance(embedding, ?) ASC LIMIT N`, filtrar por umbral.
- **KnowledgeLoader**: ingesta desde catálogo (CSV/Excel) vía Polars/PyArrow → embeddings → `INSERT ON CONFLICT DO UPDATE`.
- Aislamiento y tipado en un solo proceso (Habeas Data).

---

## 4. Pipeline Zero-Copy (Apache Arrow)

Evitar JSON intermedio: DuckDB → Arrow (RecordBatch/Table) → consumo en Python/Sandbox.

- **ArrowBridge**: `from_json`, `from_parquet`, `from_db_path`, `query_arrow`, `query_batches` (streaming), `to_pandas`, `to_parquet`, `to_ipc`, `to_llm_context` (markdown truncado).
- **StreamingBatchReader**: iterar por lotes sin materializar todo en RAM.
- **LLMContextSerializer**: tabla → markdown con schema + filas (y opcional describe).
- **SandboxDataChannel**: inyectar datos al Sandbox como Parquet (no CSV) en `/workspace/data`.
- DuckDB Python: `conn.execute("SELECT ...").arrow()` para exportación zero-copy. Modo read-only para `.duckdb` en pipelines de solo lectura.

---

## 5. Estrategia de Persistencia y Estado

- **Checkpointing LangGraph**: estados en tabla `graph_checkpoints` (DuckDB) para reanudar conversaciones.
- **Homeostasis Beliefs**: creencias del agente en tablas relacionales para auditoría.
- **Habeas Data**: vistas segregadas y anonimización en capa de persistencia; borrado granular de nodos en el grafo (derecho al olvido sin reindexar vectores).

---

*Consolidado desde: Estructura_Basada_en_Grafos_DuckDB_PGQ_GraphRAG, DuckDB_Native_RAG_Vector_Search, Pipeline_de_Datos_Zero-Copy_con_PyArrow, Estrategia_Persistencia_y_Modelamiento_BD, Sovereign_CRM_Memoria_Bicameral_DuckDB_PGQ, Subagent Spawning (LEARNED_WORKAROUND PGQ).*

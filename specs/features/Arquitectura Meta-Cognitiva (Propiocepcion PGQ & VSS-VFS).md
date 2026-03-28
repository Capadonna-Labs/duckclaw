# Arquitectura Meta-Cognitiva (Propiocepción PGQ & VSS-VFS)

**Objetivo**
Evolucionar el arnés DuckClaw hacia la autonomía de Nivel 4 dotando a los agentes de **Propiocepción** (conciencia de su propio estado y dependencias vía grafos PGQ) y un **Virtual File System Semántico (VFS)** montado sobre DuckDB VSS. Esto permitirá el Spec-Driven Management (SDM) autónomo y la gestión de catálogos complejos (ej. Asistente de Leila) sin romper el aislamiento del tenant ni la asincronía del Singleton Writer.

**Contexto**
Actualmente, el estado de LangGraph es plano y la memoria es un log pasivo (`checkpoint_deltas`). Para que el `Manager` orqueste múltiples sub-agentes (ej. `Finanz`, `LeilaSupport`) de forma dinámica, necesita entender la topología de ejecución en tiempo real (quién está bloqueado, qué tarea depende de otra). Además, para que los agentes redacten sus propias specs o busquen productos en un inventario, necesitan interactuar con el espacio vectorial como si fuera un sistema de archivos POSIX (`/catalog/blusas/roja.md`), garantizando el cumplimiento de la Ley 1581 (Habeas Data) al mantener todo encriptado dentro de `db/private/<chat_id>.duckdb`.

**Esquema de datos**

La topología tri-cameral requiere definir las tablas base relacionales y luego proyectarlas a PGQ y VSS.

*1. Tablas Base para Propiocepción (PGQ):*
```sql
CREATE TABLE IF NOT EXISTS core.graph_nodes (
    node_id VARCHAR PRIMARY KEY,
    node_type VARCHAR NOT NULL, -- 'AGENT', 'TASK', 'STATE'
    attributes JSON
);

CREATE TABLE IF NOT EXISTS core.graph_edges (
    edge_id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id VARCHAR,
    target_id VARCHAR,
    relation_type VARCHAR NOT NULL, -- 'SPAWNED', 'BLOCKED_BY', 'DEPENDS_ON'
    FOREIGN KEY (source_id) REFERENCES core.graph_nodes(node_id),
    FOREIGN KEY (target_id) REFERENCES core.graph_nodes(node_id)
);

-- Proyección PGQ (DuckDB syntax)
CREATE PROPERTY GRAPH agent_cognition
VERTEX TABLES (
    core.graph_nodes LABEL Node
)
EDGE TABLES (
    core.graph_edges SOURCE KEY (source_id) REFERENCES graph_nodes (node_id)
                     DESTINATION KEY (target_id) REFERENCES graph_nodes (node_id)
                     LABEL Relation
);
```

*2. Tablas Base para el VFS Semántico (VSS):*
```sql
CREATE TABLE IF NOT EXISTS core.vfs_files (
    file_path VARCHAR PRIMARY KEY, -- ej. '/specs/leila_returns.md'
    content TEXT NOT NULL,
    metadata JSON,
    updated_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS core.vfs_embeddings (
    chunk_id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    file_path VARCHAR,
    chunk_text TEXT,
    embedding FLOAT[384], -- Dimensión dependiente del modelo MLX local (ej. mxbai-embed-large)
    FOREIGN KEY (file_path) REFERENCES core.vfs_files(file_path) ON DELETE CASCADE
);

-- Índice HNSW local para búsqueda semántica ultrarrápida
CREATE INDEX vfs_hnsw_idx ON core.vfs_embeddings USING HNSW (embedding) WITH (metric = 'cosine');
```

**Flujo**

*A. Ciclo de Propiocepción (Lectura PGQ):*
1. El `Manager` inicia su ciclo en LangGraph. El primer nodo es `ProprioceptionNode`.
2. Ejecuta una consulta PGQ: `SELECT path FROM GRAPH_TABLE (agent_cognition MATCH (a:Node {node_type: 'AGENT'})-[r:Relation {relation_type: 'BLOCKED_BY'}]->(t:Node {node_type: 'TASK'}))`.
3. El resultado se inyecta en el `State` del grafo. El LLM ahora "sabe" qué procesos están en espera antes de planificar el siguiente paso.

*B. Ciclo VFS (Escritura y Búsqueda VSS):*
1. El agente decide crear un documento usando la tool `vfs_write`.
2. El worker Python (LangGraph) recibe el contenido, lo divide en chunks y genera los embeddings localmente usando MLX (Apple Silicon).
3. El worker emite un `StateDelta` con operación `VFS_UPSERT` que contiene el texto y los vectores.
4. El payload viaja por Redis (`duckdb_write_queue`).
5. El Singleton Writer (C++) consume la cola y ejecuta el `INSERT/UPDATE` transaccional en `core.vfs_files` y `core.vfs_embeddings`.
6. Para leer, el agente usa `vfs_semantic_grep`. El worker Python genera el embedding de la query (MLX) y hace un `SELECT` directo a DuckDB usando la distancia coseno.

**Contratos**

*Tools del Agente (Skills Atómicas):*
```python
def vfs_write(path: str, content: str, metadata: dict = None) -> str:
    """Escribe o sobrescribe un archivo en el VFS y actualiza su índice semántico."""
    pass

def vfs_semantic_grep(query: str, path_prefix: str = "/") -> list[dict]:
    """Busca fragmentos de archivos por significado semántico bajo un path específico."""
    pass

def vfs_ls(path: str) -> list[str]:
    """Lista los archivos y directorios en el VFS."""
    pass
```

*Payload Redis para Singleton Writer (VFS_UPSERT):*
```json
{
  "operation": "VFS_UPSERT",
  "chat_id": "1726618406",
  "payload": {
    "file_path": "/catalog/blusas/roja_verano.md",
    "content": "# Blusa Roja...",
    "metadata": {"price": 45000, "stock": 12},
    "chunks":[
      {"text": "Blusa roja ideal para clima cálido...", "embedding":[0.12, -0.05, ...]}
    ]
  }
}
```

**Validaciones**
1. **Path Traversal Security:** El `Normalizer` de la tool `vfs_write` debe rechazar cualquier `path` que contenga `..` o intente escapar de la raíz virtual `/`.
2. **Aislamiento de Tenant:** El Singleton Writer debe asegurar que la conexión DuckDB corresponda estrictamente al `chat_id` del payload. Un agente no puede buscar en el VFS de otro tenant.
3. **Offloading de Inferencia:** El Singleton Writer (C++) **jamás** debe calcular embeddings. Su única responsabilidad es I/O. El worker Python (MLX) debe enviar el vector ya calculado en el payload de Redis.

**Edge cases**
1. **Colisión de Escritura VFS:** Si dos sub-agentes intentan hacer `vfs_write` al mismo `file_path` simultáneamente, el Singleton Writer procesará el primero que llegue a Redis. El segundo sobrescribirá al primero (Last-Write-Wins). Para evitar pérdida de datos críticos, el `ProprioceptionNode` debe bloquear tareas concurrentes sobre el mismo recurso.
2. **Ciclos Infinitos en PGQ:** Si un agente A espera a B, y B espera a A, la consulta PGQ detectará un ciclo. El `ProprioceptionNode` debe tener una heurística para romper ciclos (ej. matar la tarea más reciente) y notificar al `Manager` del deadlock.
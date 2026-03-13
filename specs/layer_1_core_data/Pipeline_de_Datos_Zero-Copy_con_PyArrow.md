# Pipeline de Datos Zero-Copy con PyArrow

## 1. Objetivo Arquitectónico
Eliminar la serialización redundante (DuckDB → JSON → dict → objeto Python) que ocurre cada vez que `db.query()` devuelve una cadena JSON. En su lugar, exponer un pipeline **zero-copy** basado en **Apache Arrow** como formato de intercambio en memoria: DuckDB soporta exportación nativa a Arrow (`RecordBatch` / `Table`) sin deserializar a Python puro, lo que permite:
- Transferir resultados de consultas al **Sandbox Docker** como Parquet (columnar, tipado, sin parseo).
- Alimentar modelos de ML y DataFrames sin copias adicionales en RAM.
- Serializar contexto para el LLM de forma compacta y truncable (sin dumps JSON de listas de dicts).
- Exportar y consumir datos en el **GraphRAG** (`memory_nodes`, `memory_edges`) con mayor velocidad.

## 2. Diseño del Pipeline

```text
DuckClaw C++ (db.execute / db.query)
        │
        │  ① JSON fallback (actual)
        │  ② COPY TO PARQUET (DuckClaw nativo)
        ▼
ArrowBridge ──────────────────────────────────────────────────────
  ├── from_json(json_str)       → pyarrow.Table (vía duckdb in-memory)
  ├── from_parquet(path)        → pyarrow.Table (zero-copy mmap)
  ├── from_db_path(path, sql)   → pyarrow.Table (duckdb read-only)
  ├── query_arrow(sql)          → pyarrow.Table
  ├── query_batches(sql, n)     → Iterator[RecordBatch]   ← StreamingBatchReader
  ├── to_pandas(table)          → pd.DataFrame (zero_copy_only cuando es posible)
  ├── to_parquet(table, path)   → archivo .parquet
  ├── to_ipc(table, path)       → Arrow IPC / feather
  └── to_llm_context(table)     → str markdown truncado   ← LLMContextSerializer
        │
        ├── SandboxDataChannel  → Parquet en /tmp/session/data/data.parquet (rw sandbox)
        ├── GraphRAG read path  → Arrow Table de memory_nodes/memory_edges
        └── BI / LLM context    → tabla markdown compacta para el prompt
```

## 3. Módulos Core

### Módulo: `ArrowBridge`
Punto de acceso único al pipeline Arrow. Envuelve una conexión DuckDB Python (in-memory o file-based read-only).

| Método | Entrada | Salida | Notas |
|--------|---------|--------|-------|
| `from_json(json_str)` | str JSON (salida de `db.query()`) | `pa.Table` | In-memory DuckDB, sin I/O |
| `from_parquet(path)` | ruta .parquet | `pa.Table` | `pyarrow.parquet.read_table` con mmap |
| `from_db_path(db_path, sql)` | ruta .duckdb + SQL | `pa.Table` | Conexión read-only; WAL seguro |
| `query_arrow(sql)` | SQL | `pa.Table` | Usa conexión interna del bridge |
| `query_batches(sql, n)` | SQL, batch_size | `Iterator[RecordBatch]` | Para datasets > RAM |
| `to_pandas(table)` | `pa.Table` | `pd.DataFrame` | `zero_copy_only=False` (fallback seguro) |
| `to_parquet(table, path)` | `pa.Table`, ruta | `Path` | Compresión snappy por defecto |
| `to_ipc(table, path)` | `pa.Table`, ruta | `Path` | Feather v2 (lectura ultrarrápida) |
| `to_llm_context(table)` | `pa.Table` | str | Markdown table con schema + N filas |

### Módulo: `StreamingBatchReader`
Para resultados grandes (ej. dataset Olist completo). Itera sobre `RecordBatch` de `batch_size` filas sin materializar todo en RAM.

### Módulo: `LLMContextSerializer`
Convierte un `pa.Table` en un bloque de texto para el system prompt:
1. Encabezado con schema (nombre + tipo de cada columna).
2. Hasta `max_rows` filas en formato markdown.
3. Si hay más filas, añade `"... N filas más (muestra de {max_rows})"`.
4. Opcionalmente: resumen estadístico (`describe()`) para columnas numéricas.

### Módulo: `SandboxDataChannel`
Reemplaza el export CSV en `sandbox.data_inject()` por Parquet cuando PyArrow está disponible:
- Produce `data.parquet` (columnar, tipado, ≈5× más compacto que CSV para datos numéricos).
- El sandbox lee con `pd.read_parquet('/workspace/data/data.parquet')`.
- Fallback automático a CSV si PyArrow falla.

## 4. Protocolo Zero-Copy: DuckDB ↔ Arrow

DuckDB Python SDK exporta directamente a Arrow sin deserializar a Python:
```python
import duckdb
conn = duckdb.connect(":memory:")
table: pyarrow.Table = conn.execute("SELECT * FROM ...").arrow()
```
Esto evita la cadena: `binary rows → JSON string → json.loads() → list[dict]`. Los buffers de columnas de DuckDB se comparten con PyArrow via el **Arrow C Data Interface** (zero-copy real cuando los tipos son compatibles).

## 5. Ventajas de Cumplimiento (Habeas Data)
- **Parquet sobre CSV:** el Parquet incluye schema explícito con tipos, lo que elimina ambigüedades de parsing (fechas, enteros, nulls).
- **Modo read-only:** `ArrowBridge.from_db_path()` abre el archivo `.duckdb` en modo solo-lectura, garantizando que el pipeline de datos nunca puede mutar la base maestra.
- **IPC local:** los archivos Arrow IPC (Feather) son lectura por mmap del kernel, el proceso lector no requiere permisos de escritura.

## 6. Integración en el Ecosistema duckclaw

| Componente | Cambio |
|------------|--------|
| `sandbox.data_inject()` | Usa `SandboxDataChannel` → Parquet en vez de CSV |
| `bi/olist._parse_query_result()` | Fast path via `ArrowBridge.from_json()` → `to_pandas()` |
| `agents/graph_rag` | `ArrowBridge.from_db_path()` para leer `memory_nodes`/`memory_edges` |
| `agents/general_graph` | `LLMContextSerializer` para compactar resultados de herramientas |
| `pyproject.toml` | Nueva optional dep `arrow = ["duckdb>=1.0.0", "pyarrow>=14.0.0"]` |

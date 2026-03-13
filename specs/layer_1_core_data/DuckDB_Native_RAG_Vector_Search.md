# DuckDB Native RAG (Vector Similarity Search) para Catálogos

## 1. Objetivo Arquitectónico

Dotar a los trabajadores virtuales (SupportWorker, Power Seal) de **Búsqueda Semántica (RAG)** sobre catálogos de productos y bases de conocimiento, manteniendo **Cero Dependencias Externas**. Se utiliza la extensión nativa `vss` (Vector Similarity Search) de DuckDB, eliminando Pinecone/Qdrant/Milvus y garantizando soberanía total en el archivo `.duckdb`.

## 2. Esquema Vectorial (DuckDB DDL)

```sql
INSTALL vss;
LOAD vss;

CREATE TABLE catalog_items (
    sku VARCHAR PRIMARY KEY,
    name VARCHAR,
    description TEXT,
    price DECIMAL,
    stock_status VARCHAR,
    embedding FLOAT[768]
);

CREATE INDEX catalog_hnsw_idx ON catalog_items USING HNSW (embedding) WITH (metric = 'cosine');
```

Dimensión 768: nomic-embed-text, all-MiniLM-L6-v2, etc.

## 3. CatalogRetriever (Skill)

| Paso | Acción |
|------|--------|
| 1 | Vectorizar `user_query` (sentence-transformers o mlx-embedding) |
| 2 | `ORDER BY array_cosine_distance(embedding, ?) ASC LIMIT 5` |
| 3 | Filtrar por `distance < 0.3` (relevancia) |
| 4 | Retornar JSON con productos coincidentes |

## 4. KnowledgeLoader (Pipeline de Ingesta)

- **Trigger:** n8n o Telegram detecta `catalogo.csv` / `catalogo.xlsx`
- **Proceso:** Polars/PyArrow → embeddings para `name + " " + description` → `INSERT ON CONFLICT DO UPDATE`

## 5. Integración Power Seal

- `manifest.yaml`: `skills: [catalog_retriever, ...]`
- System prompt: "SIEMPRE usa catalog_retriever para consultas de producto. Si no hay resultados, agenda llamada con especialista."

## 6. Ventajas (Habeas Data)

- **Aislamiento:** Embeddings locales, sin API externa
- **Eficiencia:** DuckDB = OLAP + VSS en un solo proceso
- **Transaccionalidad:** Precio y vector siempre sincronizados

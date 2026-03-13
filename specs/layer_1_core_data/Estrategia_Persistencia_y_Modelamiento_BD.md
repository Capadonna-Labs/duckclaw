# Estrategia de Persistencia y Modelamiento de Datos DuckClaw 🦆🗄️

Para asegurar la escalabilidad y el rendimiento "Zero-Copy" en sistemas soberanos, DuckClaw implementa una arquitectura de datos híbrida basada en DuckDB.

## 1. Clasificación de Datos y Motores

| Tipo de Dato | Motor Recomendado | Justificación |
|:--- |:--- |:--- |
| **Relacional (Analítico)** | DuckDB (OLAP) | Consultas complejas en memoria, agregaciones instantáneas. |
| **No-Relacional (Estado Efímero)** | Redis | Gestión de la cola de escritura (`duckdb_write_queue`) y bloqueos de proceso. |
| **Vectorial (RAG/Memoria)** | DuckDB + VSS | Almacenamiento de embeddings local, sin dependencias de nubes vectoriales. |
| **Grafos (Relacional Semántico)** | DuckDB PGQ | Modelamiento de relaciones complejas usando SQL estándar. |

## 2. Modelamiento y Capa de Backend

### Persistencia entre Servicios
La comunicación efectiva entre el modelamiento de BD y el backend como servicio se rige por tres pilares:

1.  **Singleton Writer Bridge**: El backend NO escribe directamente en DuckDB. Envía comandos SQL a Redis. El `DB-Writer` los ejecuta secuencialmente. Esto elimina el riesgo de corrupción por accesos concurrentes (`ReadWriteOnce`).
2.  **Shared-Nothing Analytics**: Cada Worker de agente puede tener una base de datos DuckDB local para procesar tareas masivas y luego "consolidar" los resultados hacia el `Datalake` centralizado vía Parquet.
3.  **Habeas Data & Privacy**: Los datos sensibles se anonimizan en la capa de persistencia mediante vistas segregadas.

## 3. Manejo de Estados (State Management)

- **Checkpointing de LangGraph**: Los estados intermedios del grafo se persisten en una tabla `graph_checkpoints` en DuckDB. Esto permite reanudar una conversación tras un reinicio del servicio.
- **Homeostasis Beliefs**: La capa superior de agentes almacena sus "creencias" (beliefs) sobre el sistema en tablas relacionales, permitiendo auditoría SQL sobre por qué el agente tomó una decisión.

## 4. Persistencia Vectorial Local

En lugar de usar Pinecone o Milvus, DuckClaw utiliza la extensión `vss` de DuckDB:
- **Indexación**: HNSW sobre tablas nativas.
- **Querying**: Similitud coseno integrada en el SQL normal:
  ```sql
  SELECT text FROM documents 
  ORDER BY array_distance(embedding, ?) 
  LIMIT 5;
  ```

---
*Status: Architettura de Datos Versión 2.0 (Microservices Compatible)*

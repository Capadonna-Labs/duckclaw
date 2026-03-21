# Arquitectura de Memoria Triple y Plantillas de Industria (v3.0)

## 1. Objetivo Arquitectónico
Estandarizar el despliegue de DuckClaw mediante **Plantillas de Industria (Industry Templates)** que implementan una **Memoria Triple Unificada** en un único archivo DuckDB. Esta arquitectura fusiona el rigor transaccional de **SQL**, la inteligencia relacional de **PGQ (Grafos)** y la intuición semántica de **VSS (Vectores)**, permitiendo que los agentes operen sobre un sistema empresarial completo (ERP + CRM + Workflow) de forma soberana y escalable.

## 2. Estructura del Sistema de Plantillas (`The Forge`)

Las plantillas residen en `templates/industries/` y definen el "ADN" del tenant.

```text
duckclaw/templates/industries/
└── business_standard/          # Plantilla por defecto (Enterprise Core)
    ├── schema.sql              # DDL Triple (SQL + PGQ + VSS)
    ├── seed_data.sql           # Catálogos maestros (Roles, Geo, Org)
    └── manifest.yaml           # Configuración de workers y cuotas
```

## 3. Diseño del Esquema Triple (DDL Business Standard)

### Capa 1: SQL (Estructura Transaccional)
Basado en ingeniería inversa de sistemas de alta escala (Laravel/Spatie), dividido en esquemas lógicos.

```sql
-- ESQUEMA CORE: Identidad y Sesiones
CREATE SCHEMA IF NOT EXISTS core;
CREATE TABLE core.profiles (
    id VARCHAR PRIMARY KEY,
    document_number VARCHAR UNIQUE,
    full_name VARCHAR NOT NULL,
    email VARCHAR UNIQUE,
    bio TEXT,
    bio_embedding FLOAT[768], -- Capa VSS
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ESQUEMA RBAC: Control de Acceso (Spatie Style)
CREATE SCHEMA IF NOT EXISTS rbac;
CREATE TABLE rbac.roles (id VARCHAR PRIMARY KEY, name VARCHAR UNIQUE);
CREATE TABLE rbac.permissions (id VARCHAR PRIMARY KEY, name VARCHAR UNIQUE);
CREATE TABLE rbac.user_roles (
    user_id VARCHAR REFERENCES core.profiles(id),
    role_id VARCHAR REFERENCES rbac.roles(id),
    PRIMARY KEY (user_id, role_id)
);

-- ESQUEMA ORG: Estructura Jerárquica
CREATE SCHEMA IF NOT EXISTS org;
CREATE TABLE org.units (
    id VARCHAR PRIMARY KEY,
    parent_id VARCHAR REFERENCES org.units(id),
    name VARCHAR NOT NULL,
    type VARCHAR -- 'department', 'team'
);
CREATE TABLE org.positions (
    id VARCHAR PRIMARY KEY,
    unit_id VARCHAR REFERENCES org.units(id),
    title VARCHAR NOT NULL,
    reports_to VARCHAR REFERENCES org.positions(id)
);

-- ESQUEMA FLOW: Motor de Procesos
CREATE SCHEMA IF NOT EXISTS flow;
CREATE TABLE flow.instances (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    status VARCHAR DEFAULT 'pending',
    summary TEXT,
    summary_embedding FLOAT[768] -- Capa VSS
);
```

### Capa 2: PGQ (Memoria Estructural de Grafos)
Proyecta relaciones complejas sobre las tablas SQL para permitir razonamiento multi-salto.

```sql
INSTALL pgq;
LOAD pgq;

CREATE OR REPLACE PROPERTY GRAPH enterprise_kg
VERTEX TABLES (
    core.profiles LABEL person,
    org.units LABEL unit,
    org.positions LABEL position,
    flow.instances LABEL workflow
)
EDGE TABLES (
    rbac.user_roles 
        SOURCE KEY (user_id) REFERENCES core.profiles (id)
        DESTINATION KEY (role_id) REFERENCES rbac.roles (id)
        LABEL has_role,
    org.positions
        SOURCE KEY (id) REFERENCES org.positions (id)
        DESTINATION KEY (reports_to) REFERENCES org.positions (id)
        LABEL reports_to
);
```

### Capa 3: VSS (Memoria Semántica Vectorial)
Habilita búsqueda RAG nativa y detección de similitudes sin salir de DuckDB.

```sql
INSTALL vss;
LOAD vss;

-- Índices HNSW para latencia sub-milisegundo
CREATE INDEX profile_vss_idx ON core.profiles USING HNSW (bio_embedding) WITH (metric = 'cosine');
CREATE INDEX flow_vss_idx ON flow.instances USING HNSW (summary_embedding) WITH (metric = 'cosine');
```

## 4. Especificación de Skill: `UnifiedMemoryOrchestrator`

Este nodo en LangGraph decide qué capa de memoria consultar según la intención.

*   **Lógica de Decisión:**
    1.  **¿Es contable/exacto?** -> Ejecutar **SQL** (ej. "Saldos", "Conteo de usuarios").
    2.  **¿Es relacional/jerárquico?** -> Ejecutar **PGQ** (ej. "¿Quién aprueba esto?", "¿A qué equipo pertenece X?").
    3.  **¿Es conceptual/difuso?** -> Ejecutar **VSS** (ej. "Busca expertos en...", "Casos similares a...").
*   **Contrato:** El agente recibe un contexto unificado: `{"sql_data": [...], "graph_relations": [...], "semantic_matches": [...]}`.

## 5. Protocolo de Aprovisionamiento (`duckops init`)

El comando de inicialización automatiza la creación del entorno:

1.  **Tenant Isolation:** Crea `db/private/{tenant_id}.duckdb`.
2.  **Schema Injection:** Ejecuta el `schema.sql` de la plantilla seleccionada.
3.  **Master Data Seeding:** Carga `seed_data.sql` (ej. inserta los roles `admin`, `manager`, `viewer`).
4.  **Worker Activation:** Registra los agentes base en la tabla `main.agent_config`.

## 6. Garantías de Soberanía y Habeas Data (Colombia)

*   **Aislamiento Físico:** Cada empresa tiene su propio archivo DuckDB. No hay riesgo de cruce de datos a nivel de motor.
*   **Auditoría Nativa:** Todas las tablas incluyen columnas `created_by` y `updated_by` referenciando a `core.profiles`.
*   **Derecho al Olvido:** Al borrar un perfil en `core.profiles`, las llaves foráneas en SQL y las aristas en PGQ se eliminan automáticamente (ON DELETE CASCADE).

---

## 7. Nota de implementación (monorepo DuckClaw)

Alineación con el código y rutas reales:

| Tema | Implementación en repo |
| :--- | :--- |
| **Ruta de plantillas** | `packages/agents/src/duckclaw/forge/templates/industries/<id>/` (no `duckclaw/templates/industries/`). |
| **Extensión de grafos** | **duckpgq** (`INSTALL duckpgq FROM community;` / `LOAD duckpgq;`), no `pgq` como en el ejemplo histórico del §3. |
| **Aislamiento por tenant (Multi-Vault)** | Archivo `db/private/{tenant_id}/default.duckdb` (función `ensure_tenant_industry_db` en `duckclaw.vaults`). El `duckops init --industry <id>` exporta `DUCKCLAW_TENANT_ID` y `DUCKCLAW_INDUSTRY_TEMPLATE` al wizard, que aplica `schema.sql` + `seed_data.sql` y semillas en `main.agent_config`. |
| **Skill en LangGraph** | Herramienta `unified_memory` inyectada en `general_graph` si `DUCKCLAW_INDUSTRY_TEMPLATE` está definido o si `unified_memory` figura en `tools_spec`. |
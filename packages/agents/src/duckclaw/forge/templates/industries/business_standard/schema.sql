-- Industry template: business_standard (Memoria Triple v3.0)
-- DuckDB: no FK entre esquemas distintos. Auditoría user_id como VARCHAR sin FK cruzada.
-- Perfiles: self-FK en core.profiles para created_by/updated_by (mismo esquema).

INSTALL duckpgq FROM community;
LOAD duckpgq;

INSTALL vss;
LOAD vss;

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS rbac;
CREATE SCHEMA IF NOT EXISTS org;
CREATE SCHEMA IF NOT EXISTS flow;

CREATE TABLE IF NOT EXISTS core.profiles (
    id VARCHAR PRIMARY KEY,
    document_number VARCHAR UNIQUE,
    full_name VARCHAR NOT NULL,
    email VARCHAR UNIQUE,
    bio TEXT,
    bio_embedding FLOAT[768],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR,
    updated_by VARCHAR,
    FOREIGN KEY (created_by) REFERENCES core.profiles(id),
    FOREIGN KEY (updated_by) REFERENCES core.profiles(id)
);

CREATE TABLE IF NOT EXISTS rbac.roles (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR,
    updated_by VARCHAR
);

CREATE TABLE IF NOT EXISTS rbac.permissions (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR,
    updated_by VARCHAR
);

CREATE TABLE IF NOT EXISTS rbac.user_roles (
    user_id VARCHAR NOT NULL,
    role_id VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR,
    updated_by VARCHAR,
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (role_id) REFERENCES rbac.roles(id)
);

CREATE TABLE IF NOT EXISTS org.units (
    id VARCHAR PRIMARY KEY,
    parent_id VARCHAR,
    name VARCHAR NOT NULL,
    type VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR,
    updated_by VARCHAR,
    FOREIGN KEY (parent_id) REFERENCES org.units(id)
);

CREATE TABLE IF NOT EXISTS org.positions (
    id VARCHAR PRIMARY KEY,
    unit_id VARCHAR,
    title VARCHAR NOT NULL,
    reports_to VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR,
    updated_by VARCHAR,
    FOREIGN KEY (unit_id) REFERENCES org.units(id),
    FOREIGN KEY (reports_to) REFERENCES org.positions(id)
);

CREATE TABLE IF NOT EXISTS flow.instances (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    status VARCHAR DEFAULT 'pending',
    summary TEXT,
    summary_embedding FLOAT[768],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR,
    updated_by VARCHAR
);

DROP PROPERTY GRAPH IF EXISTS enterprise_kg;

CREATE PROPERTY GRAPH enterprise_kg
VERTEX TABLES (
    core.profiles LABEL person,
    org.units LABEL unit,
    org.positions LABEL position,
    flow.instances LABEL workflow,
    rbac.roles LABEL role
)
EDGE TABLES (
    rbac.user_roles
        SOURCE KEY (user_id) REFERENCES core.profiles (id)
        DESTINATION KEY (role_id) REFERENCES rbac.roles (id)
        LABEL has_role,
    org.positions
        SOURCE KEY (id) REFERENCES org.positions (id)
        DESTINATION KEY (reports_to) REFERENCES org.positions (id)
        LABEL reports_to_edge
);

CREATE INDEX IF NOT EXISTS profile_vss_idx ON core.profiles USING HNSW (bio_embedding) WITH (metric = 'cosine');
CREATE INDEX IF NOT EXISTS flow_vss_idx ON flow.instances USING HNSW (summary_embedding) WITH (metric = 'cosine');

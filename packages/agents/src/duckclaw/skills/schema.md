---
name: olist-schema
description: Consultas sobre tablas, esquema y estructura de la base de datos Olist
allowed-tools: list_tables
---

# Schema / Tablas

## Cuándo activar

- "¿Cuántas tablas hay?"
- "¿Qué tablas hay disponibles?"
- "Esquema de la base"
- "Estructura de la DB"

## Herramienta

- `list_tables`: lista las tablas en information_schema.

## Regla

Siempre usa `list_tables` para preguntas sobre tablas o esquema. Responde con el conteo y los nombres.

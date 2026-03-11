# Especificación Técnica: Sovereign CRM basado en Memoria Bicameral (DuckDB PGQ)

## 1. Objetivo Arquitectónico

Implementar el motor de perfilamiento de clientes (Leads) utilizando la extensión PGQ de DuckDB. En lugar de tablas relacionales rígidas, el agente construirá un **Grafo de Conocimiento Comercial** dinámico. Esto permite inferencia multi-salto (Multi-hop reasoning) para ventas cruzadas (Cross-selling) y un contexto hiper-personalizado sin alterar el esquema de la base de datos.

## 2. Ontología del Grafo Comercial (PGQ Schema)

El esquema base de `memory_nodes` y `memory_edges` se especializa para el dominio B2B (Power Seal).

### A. Definición de Nodos (Vértices)

- **Lead:** `{phone: "+57323...", name: "Carlos", lead_score: 85}`
- **Company:** `{name: "EPM", sector: "Acueducto"}`
- **Product:** `{sku: "3121AI", category: "Abrazadera"}`

### B. Definición de Aristas (Relaciones)

- `[:WORKS_AT]` → (Lead → Company)
- `[:INTERESTED_IN {intent_level: "high", last_inquiry: "2026-03-11"}]` → (Lead → Product)
- `[:PURCHASED {quantity: 50, date: "2026-01-15"}]` → (Lead → Product)

### C. Declaración del Grafo en DuckDB

```sql
CREATE OR REPLACE PROPERTY GRAPH powerseal_crm
VERTEX TABLES (
    memory_nodes LABEL entity
)
EDGE TABLES (
    memory_edges SOURCE KEY (source_id) REFERENCES memory_nodes (node_id)
                 DESTINATION KEY (target_id) REFERENCES memory_nodes (node_id)
                 LABEL relation
);
```

## 3. Especificación de Skill: GraphLeadProfiler (Write Pipeline)

Este nodo asíncrono (Background Task en ARQ) procesa la conversación para extraer tripletas comerciales.

**Entrada:** Historial de chat reciente.

**Lógica Interna:**
1. **Extracción de Tripletas (LLM):** El modelo analiza el chat y extrae relaciones.
   - Ejemplo: Usuario dice: "Soy Carlos de EPM, necesito cotizar la abrazadera 3121AI urgente".
   - Salida LLM: `[("+57323...", "WORKS_AT", "EPM"), ("+57323...", "INTERESTED_IN", "3121AI")]`
2. **Upsert en DuckDB:** Insertar o actualizar los nodos y aristas correspondientes en `memory_nodes` y `memory_edges`.
3. **Cálculo de Lead Score:** Si la relación es INTERESTED_IN y el contexto denota urgencia, actualizar la propiedad `lead_score` del nodo Lead.

## 4. Especificación de Skill: GraphContextInjector (Read Pipeline)

Antes de que el SupportWorker responda, este nodo inyecta el contexto del grafo en el System Prompt.

**Entrada:** `user_phone` (ID del nodo Lead) o `lead_id` (session_id/chat_id como fallback).

**Lógica Interna (DuckDB PGQ):**
- Ejecutar consulta de emparejamiento de patrones para obtener el perfil 360 del cliente.
- Formatear el resultado como Markdown.

**Salida:** Bloque `<lead_context>` inyectado en el prompt.

## 5. Ventajas Arquitectónicas

- **Cross-Selling Inteligente:** Consultas multi-salto para recomendaciones.
- **Flexibilidad:** Nuevas relaciones ([:COMPLAINED_ABOUT], [:GARANTÍA]) sin ALTER TABLE.
- **Habeas Data:** Borrar un nodo Lead elimina en cascada todas sus aristas.

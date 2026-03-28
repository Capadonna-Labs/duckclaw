# Asistente de Leila — MVP Telegram

## Objetivo
Agente de ventas para Leila Store en Telegram. Muestra catálogo,
toma pedidos y notifica al admin. Sin pagos, sin inventario en tiempo real.

## Tenant
- Canal: Telegram DM
- Admin: tu mamá (chat_id por definir)
- Beta testers: tu mamá, tu hermana, tú

## Herramientas (3)

### 1. `consultar_catalogo`
SELECT * FROM leila_products WHERE activo = true
Responde con nombre, descripción, tallas, precio, foto_url.

### 2. `registrar_pedido`
INSERT en leila_orders (chat_id, producto_id, talla, timestamp)
Notifica al admin por DM vía outbound webhook:
"🛍️ Nuevo pedido: [producto] talla [X] de [@usuario]"

### 3. `escalar_a_leila`
Reenvía el mensaje al admin con contexto.
Úsala cuando: precio especial, personalización, duda de talla.

## Schema DuckDB

CREATE TABLE leila_products (
    id VARCHAR PRIMARY KEY,
    nombre VARCHAR,
    descripcion TEXT,
    tallas VARCHAR[],
    precio INTEGER,
    foto_url VARCHAR,
    activo BOOLEAN DEFAULT true
);

CREATE TABLE leila_orders (
    order_id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id VARCHAR,
    producto_id VARCHAR,
    talla VARCHAR,
    nota TEXT,
    status VARCHAR DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT current_timestamp
);

## Comandos Fly

/catalogo — muestra productos activos (lee `shared.main.leila_products` cuando el gateway tiene `DUCKCLAW_SHARED_DB_PATH` y ATTACH `shared` tras validar ruta)
/pedido <producto> <talla> — registra pedido (`shared.main.leila_orders` en el mismo .duckdb compartido)
/ayuda — explica cómo comprar

## Flujo de conversación

Cliente saluda → agente presenta Leila Store brevemente
Cliente pregunta producto → consultar_catalogo
Cliente quiere comprar → registrar_pedido → confirmar + notificar admin
Cliente pregunta algo complejo → escalar_a_leila

## Personalidad
Cálida, directa, femenina. Conoce la ropa y ayuda a elegir talla.
Nunca inventa stock ni precios. Si no sabe, escala.

## Fuera de scope MVP
- Pagos
- Inventario automático
- WhatsApp (fase 2)
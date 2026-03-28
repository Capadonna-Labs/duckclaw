-- LeilaAssistant — MVP tienda de ropa (catálogo y pedidos en main.*)
-- Spec: specs/features/Asistente de Leila — MVP Telegram.md
CREATE TABLE IF NOT EXISTS main.leila_products (
    id VARCHAR PRIMARY KEY,
    nombre VARCHAR,
    descripcion TEXT,
    tallas VARCHAR[],
    precio INTEGER,
    foto_url VARCHAR,
    activo BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS main.leila_orders (
    order_id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id VARCHAR,
    producto_id VARCHAR,
    talla VARCHAR,
    nota TEXT,
    status VARCHAR DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT current_timestamp
);

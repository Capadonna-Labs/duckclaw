"""
Funciones DuckClaw para la prueba BI iData Global (Olist).

Uso en notebooks:
    import duckclaw
    from duckclaw.bi import load_olist_data, get_top_customers_by_sales, ...

    db = duckclaw.DuckClaw("olist.duckdb")
    load_olist_data(db, "data")
    get_top_customers_by_sales(db, limit=10)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

# Tablas y archivos CSV esperados
_CSV_MAP = [
    ("olist_orders_dataset.csv", "olist_orders"),
    ("olist_customers_dataset.csv", "olist_customers"),
    ("olist_order_items_dataset.csv", "olist_order_items"),
    ("olist_order_payments_dataset.csv", "olist_order_payments"),
    ("olist_order_reviews_dataset.csv", "olist_order_reviews"),
    ("olist_products_dataset.csv", "olist_products"),
    ("olist_sellers_dataset.csv", "olist_sellers"),
    ("product_category_name_translation.csv", "product_category_name_translation"),
    ("olist_geolocation_dataset.csv", "olist_geolocation"),
]

# Esquema explícito por CSV (columnas y tipos DuckDB) para carga controlada
_CSV_SCHEMAS: dict[str, dict[str, str]] = {
    "olist_orders_dataset.csv": {
        "order_id": "VARCHAR",
        "customer_id": "VARCHAR",
        "order_status": "VARCHAR",
        "order_purchase_timestamp": "VARCHAR",
        "order_approved_at": "VARCHAR",
        "order_delivered_carrier_date": "VARCHAR",
        "order_delivered_customer_date": "VARCHAR",
        "order_estimated_delivery_date": "VARCHAR",
    },
    "olist_customers_dataset.csv": {
        "customer_id": "VARCHAR",
        "customer_unique_id": "VARCHAR",
        "customer_zip_code_prefix": "INTEGER",
        "customer_city": "VARCHAR",
        "customer_state": "VARCHAR",
    },
    "olist_order_items_dataset.csv": {
        "order_id": "VARCHAR",
        "order_item_id": "INTEGER",
        "product_id": "VARCHAR",
        "seller_id": "VARCHAR",
        "shipping_limit_date": "VARCHAR",
        "price": "DECIMAL(10,2)",
        "freight_value": "DECIMAL(10,2)",
    },
    "olist_order_payments_dataset.csv": {
        "order_id": "VARCHAR",
        "payment_sequential": "INTEGER",
        "payment_type": "VARCHAR",
        "payment_installments": "INTEGER",
        "payment_value": "DECIMAL(10,2)",
    },
    "olist_order_reviews_dataset.csv": {
        "review_id": "VARCHAR",
        "order_id": "VARCHAR",
        "review_score": "INTEGER",
        "review_comment_title": "VARCHAR",
        "review_comment_message": "VARCHAR",
        "review_creation_date": "VARCHAR",
        "review_answer_timestamp": "VARCHAR",
    },
    "olist_products_dataset.csv": {
        "product_id": "VARCHAR",
        "product_category_name": "VARCHAR",
        "product_name_lenght": "INTEGER",
        "product_description_lenght": "INTEGER",
        "product_photos_qty": "INTEGER",
        "product_weight_g": "DECIMAL(10,2)",
        "product_length_cm": "DECIMAL(10,2)",
        "product_height_cm": "DECIMAL(10,2)",
        "product_width_cm": "DECIMAL(10,2)",
    },
    "olist_sellers_dataset.csv": {
        "seller_id": "VARCHAR",
        "seller_zip_code_prefix": "INTEGER",
        "seller_city": "VARCHAR",
        "seller_state": "VARCHAR",
    },
    "product_category_name_translation.csv": {
        "product_category_name": "VARCHAR",
        "product_category_name_english": "VARCHAR",
    },
    "olist_geolocation_dataset.csv": {
        "geolocation_zip_code_prefix": "INTEGER",
        "geolocation_lat": "DOUBLE",
        "geolocation_lng": "DOUBLE",
        "geolocation_city": "VARCHAR",
        "geolocation_state": "VARCHAR",
    },
}


def _path_csv(data_dir: str, filename: str) -> str:
    """Ruta absoluta al CSV para DuckDB read_csv_auto."""
    p = Path(data_dir).resolve() / filename
    return str(p).replace("\\", "/")


def _parse_query_result(db: Any, sql: str) -> list[dict[str, Any]]:
    """Ejecuta db.query(sql) y devuelve lista de dicts."""
    raw = db.query(sql)
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    return data if isinstance(data, list) else []


def _build_columns_sql(schema: dict[str, str]) -> str:
    """Construye el literal DuckDB para el parámetro columns de read_csv."""
    parts = [f"'{k}': '{v}'" for k, v in schema.items()]
    return "{" + ", ".join(parts) + "}"


def load_olist_data(
    db: Any,
    data_dir: str,
    *,
    skip_missing: bool = False,
    use_schema: bool = True,
) -> dict[str, int]:
    """
    Carga todos los CSV de Olist en la base DuckClaw.

    - db: instancia de duckclaw.DuckClaw (o compatible execute/query).
    - data_dir: ruta al directorio que contiene los CSV (ej. "data" o "./data").
    - skip_missing: si True, no falla si falta un CSV (ej. geolocation).
    - use_schema: si True (por defecto), usa esquema explícito para tipos correctos.

    Devuelve un dict con el nombre de cada tabla y la cantidad de filas cargadas.
    """
    data_path = Path(data_dir).resolve()
    counts: dict[str, int] = {}

    for filename, table in _CSV_MAP:
        csv_path = data_path / filename
        if not csv_path.exists():
            if skip_missing:
                continue
            raise FileNotFoundError(f"No se encontró: {csv_path}")

        path_str = _path_csv(data_dir, filename)
        path_str_esc = path_str.replace("'", "''")
        db.execute(f"DROP TABLE IF EXISTS {table}")

        if use_schema and filename in _CSV_SCHEMAS:
            cols_sql = _build_columns_sql(_CSV_SCHEMAS[filename])
            db.execute(
                f"CREATE TABLE {table} AS SELECT * FROM read_csv('{path_str_esc}', "
                f"columns={cols_sql}, header=true)"
            )
        else:
            db.execute(
                f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto('{path_str_esc}')"
            )
        r = _parse_query_result(db, f"SELECT COUNT(*) AS n FROM {table}")
        counts[table] = int(r[0]["n"]) if r else 0

    if not counts:
        raise RuntimeError(
            f"No se cargó ninguna tabla Olist. Revisa data_dir='{data_dir}' "
            "o ejecuta desde la raíz del repo."
        )
    return counts


def get_top_customers_by_sales(db: Any, limit: int = 20) -> list[dict[str, Any]]:
    """
    Clientes que más generan ventas (por valor total de pedidos entregados).
    Pregunta de negocio 2.1.
    """
    sql = f"""
    WITH order_value AS (
        SELECT o.order_id, o.customer_id, SUM(oi.price + oi.freight_value) AS total
        FROM olist_orders o
        JOIN olist_order_items oi ON oi.order_id = o.order_id
        WHERE o.order_status = 'delivered'
        GROUP BY o.order_id, o.customer_id
    ),
    customer_sales AS (
        SELECT customer_id, SUM(total) AS total_sales, COUNT(*) AS num_orders
        FROM order_value
        GROUP BY customer_id
    )
    SELECT c.customer_id, c.customer_city, c.customer_state,
           cs.total_sales, cs.num_orders
    FROM customer_sales cs
    JOIN olist_customers c ON c.customer_id = cs.customer_id
    ORDER BY cs.total_sales DESC
    LIMIT {int(limit)}
    """
    return _parse_query_result(db, sql)


def get_customers_to_retain(
    db: Any,
    limit: int = 20,
    min_orders: int = 2,
) -> list[dict[str, Any]]:
    """
    Clientes candidatos a fidelizar: recurrentes y con buen valor.
    Pregunta de negocio 2.2.
    """
    sql = f"""
    WITH order_value AS (
        SELECT o.order_id, o.customer_id, SUM(oi.price + oi.freight_value) AS total
        FROM olist_orders o
        JOIN olist_order_items oi ON oi.order_id = o.order_id
        WHERE o.order_status = 'delivered'
        GROUP BY o.order_id, o.customer_id
    ),
    customer_agg AS (
        SELECT customer_id,
               SUM(total) AS total_sales,
               COUNT(*) AS num_orders
        FROM order_value
        GROUP BY customer_id
        HAVING COUNT(*) >= {int(min_orders)}
    )
    SELECT c.customer_id, c.customer_city, c.customer_state,
           ca.total_sales, ca.num_orders
    FROM customer_agg ca
    JOIN olist_customers c ON c.customer_id = ca.customer_id
    ORDER BY ca.num_orders DESC, ca.total_sales DESC
    LIMIT {int(limit)}
    """
    return _parse_query_result(db, sql)


def get_top_sellers(db: Any, limit: int = 20) -> list[dict[str, Any]]:
    """
    Mejores vendedores por valor total vendido (pedidos entregados).
    Pregunta de negocio 2.3.
    """
    sql = f"""
    SELECT s.seller_id, s.seller_city, s.seller_state,
           SUM(oi.price + oi.freight_value) AS total_sales,
           COUNT(DISTINCT oi.order_id) AS num_orders
    FROM olist_order_items oi
    JOIN olist_orders o ON o.order_id = oi.order_id AND o.order_status = 'delivered'
    JOIN olist_sellers s ON s.seller_id = oi.seller_id
    GROUP BY s.seller_id, s.seller_city, s.seller_state
    ORDER BY total_sales DESC
    LIMIT {int(limit)}
    """
    return _parse_query_result(db, sql)


def get_delivery_metrics(db: Any) -> list[dict[str, Any]]:
    """
    Promedio de tiempos de entrega (días desde compra hasta entrega).
    Pregunta de negocio 2.4.
    """
    sql = """
    SELECT
        COUNT(*) AS delivered_orders,
        ROUND(AVG(DATE_DIFF('day', order_purchase_timestamp::TIMESTAMP, order_delivered_customer_date::TIMESTAMP))::DECIMAL(10,2), 2) AS avg_delivery_days,
        ROUND(MIN(DATE_DIFF('day', order_purchase_timestamp::TIMESTAMP, order_delivered_customer_date::TIMESTAMP))::DECIMAL(10,2), 2) AS min_days,
        ROUND(MAX(DATE_DIFF('day', order_purchase_timestamp::TIMESTAMP, order_delivered_customer_date::TIMESTAMP))::DECIMAL(10,2), 2) AS max_days
    FROM olist_orders
    WHERE order_status = 'delivered'
      AND order_delivered_customer_date IS NOT NULL
      AND order_purchase_timestamp IS NOT NULL
    """
    return _parse_query_result(db, sql)


def get_delivery_critical_cases(
    db: Any,
    days_threshold: int = 20,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Casos críticos: entregas que superan un número de días.
    Pregunta de negocio 2.4.
    """
    sql = f"""
    WITH delivery_days AS (
        SELECT
            order_id,
            order_purchase_timestamp,
            order_delivered_customer_date,
            DATE_DIFF('day', order_purchase_timestamp::TIMESTAMP, order_delivered_customer_date::TIMESTAMP) AS days
        FROM olist_orders
        WHERE order_status = 'delivered'
          AND order_delivered_customer_date IS NOT NULL
          AND order_purchase_timestamp IS NOT NULL
    )
    SELECT order_id, order_purchase_timestamp, order_delivered_customer_date,
           ROUND(days::DECIMAL(10,2), 2) AS delivery_days
    FROM delivery_days
    WHERE days > {int(days_threshold)}
    ORDER BY days DESC
    LIMIT {int(limit)}
    """
    return _parse_query_result(db, sql)


def get_sales_summary(db: Any) -> list[dict[str, Any]]:
    """Resumen ejecutivo: ventas totales, ticket promedio, pedidos."""
    sql = """
    SELECT
        COUNT(DISTINCT o.order_id) AS total_orders,
        ROUND(SUM(oi.price + oi.freight_value)::DECIMAL(14,2), 2) AS total_sales,
        ROUND(AVG(order_total)::DECIMAL(14,2), 2) AS avg_ticket
    FROM (
        SELECT order_id, SUM(price + freight_value) AS order_total
        FROM olist_order_items
        GROUP BY order_id
    ) tot
    JOIN olist_orders o ON o.order_id = tot.order_id AND o.order_status = 'delivered'
    CROSS JOIN (SELECT SUM(price + freight_value) AS s FROM olist_order_items oi2 JOIN olist_orders o2 ON o2.order_id = oi2.order_id AND o2.order_status = 'delivered') _x
    CROSS JOIN LATERAL (SELECT SUM(oi.price + oi.freight_value) FROM olist_order_items oi JOIN olist_orders oo ON oo.order_id = oi.order_id AND oo.order_status = 'delivered') _sum(tt)
    JOIN olist_order_items oi ON oi.order_id = o.order_id
    """
    # Versión más simple sin subconsulta lateral
    sql = """
    WITH delivered_value AS (
        SELECT o.order_id, SUM(oi.price + oi.freight_value) AS order_total
        FROM olist_orders o
        JOIN olist_order_items oi ON oi.order_id = o.order_id
        WHERE o.order_status = 'delivered'
        GROUP BY o.order_id
    )
    SELECT
        COUNT(*) AS total_orders,
        ROUND(SUM(order_total)::DECIMAL(14,2), 2) AS total_sales,
        ROUND(AVG(order_total)::DECIMAL(14,2), 2) AS avg_ticket
    FROM delivered_value
    """
    return _parse_query_result(db, sql)


def get_review_metrics(db: Any) -> list[dict[str, Any]]:
    """Métricas de satisfacción: puntuación media y distribución de reviews."""
    sql = """
    SELECT
        ROUND(AVG(review_score)::DECIMAL(5,2), 2) AS avg_score,
        COUNT(*) AS total_reviews,
        SUM(CASE WHEN review_score >= 4 THEN 1 ELSE 0 END) AS good_reviews,
        SUM(CASE WHEN review_score <= 2 THEN 1 ELSE 0 END) AS bad_reviews
    FROM olist_order_reviews
    """
    return _parse_query_result(db, sql)


def list_tables(db: Any) -> list[dict[str, Any]]:
    """Lista las tablas disponibles en la base de datos."""
    sql = (
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    )
    return _parse_query_result(db, sql)


def describe_table(db: Any, table_name: str) -> list[dict[str, Any]]:
    """Describe las columnas de una tabla. table_name: solo letras, números y _."""
    import re
    safe = (table_name or "").strip()
    if not safe or not re.match(r"^[a-zA-Z0-9_]+$", safe):
        return []
    sql = (
        "SELECT column_name, data_type FROM information_schema.columns "
        f"WHERE table_schema = 'main' AND table_name = '{safe}' ORDER BY ordinal_position"
    )
    return _parse_query_result(db, sql)


def get_sales_by_month(
    db: Any,
    year: Optional[int] = None,
    limit: int = 24,
) -> list[dict[str, Any]]:
    """
    Ventas totales por mes (pedidos entregados).
    year: filtrar por año (ej. 2018). Si None, todos los años.
    """
    where = "WHERE o.order_status = 'delivered'"
    if year is not None:
        where += f" AND strftime(o.order_purchase_timestamp::TIMESTAMP, '%Y') = '{int(year)}'"
    sql = f"""
    SELECT
        strftime(o.order_purchase_timestamp::TIMESTAMP, '%Y-%m') AS month,
        ROUND(SUM(oi.price + oi.freight_value)::DECIMAL(14,2), 2) AS total_sales,
        COUNT(DISTINCT o.order_id) AS num_orders
    FROM olist_orders o
    JOIN olist_order_items oi ON oi.order_id = o.order_id
    {where}
    GROUP BY strftime(o.order_purchase_timestamp::TIMESTAMP, '%Y-%m')
    ORDER BY month
    LIMIT {int(limit)}
    """
    return _parse_query_result(db, sql)


def get_category_sales(db: Any, limit: int = 15) -> list[dict[str, Any]]:
    """Ventas por categoría de producto (con nombre en inglés si existe)."""
    sql = f"""
    SELECT
        COALESCE(t.product_category_name_english, p.product_category_name) AS category,
        ROUND(SUM(oi.price + oi.freight_value)::DECIMAL(14,2), 2) AS total_sales,
        COUNT(DISTINCT oi.order_id) AS num_orders
    FROM olist_order_items oi
    JOIN olist_orders o ON o.order_id = oi.order_id AND o.order_status = 'delivered'
    JOIN olist_products p ON p.product_id = oi.product_id
    LEFT JOIN product_category_name_translation t ON t.product_category_name = p.product_category_name
    GROUP BY COALESCE(t.product_category_name_english, p.product_category_name)
    ORDER BY total_sales DESC
    LIMIT {int(limit)}
    """
    return _parse_query_result(db, sql)

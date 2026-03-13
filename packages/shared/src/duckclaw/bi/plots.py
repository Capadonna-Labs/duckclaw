"""
Gráficas con DuckClaw: matplotlib y seaborn a partir de datos Olist.

Uso en notebooks:
    from duckclaw.bi import plot_category_sales_bar, plot_top_sellers_bar, ...
    plot_category_sales_bar(db, save_dir="output")
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional


def _ensure_save_dir(save_dir: str) -> Path:
    p = Path(save_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get_data(db: Any, getter: Any, **kwargs: Any) -> list[dict]:
    import json
    raw = getter(db, **kwargs)
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip().startswith("[") else []
    return list(raw) if raw else []


def plot_category_sales_bar(
    db: Any,
    save_dir: str = "output",
    limit: int = 12,
    filename: str = "ventas_por_categoria.png",
) -> str:
    """Gráfico de barras: ventas por categoría de producto (matplotlib)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: instala matplotlib (pip install matplotlib)"
    from duckclaw.bi.olist import get_category_sales
    data = _get_data(db, get_category_sales, limit=limit)
    if not data:
        return "No hay datos para graficar."
    labels = [d.get("category", "N/A")[:20] for d in data]
    values = [float(d.get("total_sales", 0)) for d in data]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.barh(range(len(labels)), values, color="steelblue", alpha=0.85)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Ventas totales")
    ax.set_title("Ventas por categoría de producto")
    fig.tight_layout()
    out = _ensure_save_dir(save_dir) / filename
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return f"Gráfica guardada: {out}"


def plot_category_sales_pie(
    db: Any,
    save_dir: str = "output",
    limit: int = 5,
    filename: str = "ventas_por_categoria_torta.png",
) -> str:
    """Gráfico de torta: top categorías por ventas (matplotlib)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: instala matplotlib (pip install matplotlib)"
    from duckclaw.bi.olist import get_category_sales
    data = _get_data(db, get_category_sales, limit=limit)
    if not data:
        return "No hay datos para graficar."
    labels = [d.get("category", "N/A")[:25] for d in data]
    values = [float(d.get("total_sales", 0)) for d in data]
    fig, ax = plt.subplots(figsize=(8, 6))
    colors = plt.cm.Set3.colors[: len(labels)]
    ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90, colors=colors)
    ax.set_title("Top categorías por ventas (diagrama de torta)")
    fig.tight_layout()
    out = _ensure_save_dir(save_dir) / filename
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return f"Gráfica guardada: {out}"


def plot_top_sellers_bar(
    db: Any,
    save_dir: str = "output",
    limit: int = 10,
    filename: str = "top_vendedores.png",
) -> str:
    """Gráfico de barras: mejores vendedores por ventas (matplotlib)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: instala matplotlib (pip install matplotlib)"
    from duckclaw.bi.olist import get_top_sellers
    data = _get_data(db, get_top_sellers, limit=limit)
    if not data:
        return "No hay datos para graficar."
    labels = [f"{d.get('seller_city','')} ({d.get('seller_id','')[:8]}...)" for d in data]
    values = [float(d.get("total_sales", 0)) for d in data]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(range(len(labels)), values, color="coral", alpha=0.85)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Ventas totales")
    ax.set_title("Top vendedores por ventas")
    fig.tight_layout()
    out = _ensure_save_dir(save_dir) / filename
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return f"Gráfica guardada: {out}"


def plot_review_score_pie(
    db: Any,
    save_dir: str = "output",
    filename: str = "reviews_puntuacion.png",
) -> str:
    """Gráfico de torta: distribución de puntuaciones de reviews (matplotlib)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: instala matplotlib (pip install matplotlib)"
    import json
    raw = db.query(
        "SELECT review_score, COUNT(*) AS n FROM olist_order_reviews GROUP BY review_score ORDER BY review_score"
    )
    rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
    if not rows:
        return "No hay datos para graficar."
    labels = [f"Puntuación {r.get('review_score', '')}" for r in rows]
    sizes = [int(r.get("n", 0)) for r in rows]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90, colors=plt.cm.Pastel1.colors)
    ax.set_title("Distribución de puntuaciones de reviews")
    fig.tight_layout()
    out = _ensure_save_dir(save_dir) / filename
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return f"Gráfica guardada: {out}"


def plot_delivery_days_histogram(
    db: Any,
    save_dir: str = "output",
    filename: str = "dias_entrega_histograma.png",
) -> str:
    """Histograma: días de entrega (seaborn si está, si no matplotlib)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: instala matplotlib (pip install matplotlib)"
    import json
    sql = """
    WITH t AS (
        SELECT DATE_DIFF('day', order_purchase_timestamp::TIMESTAMP, order_delivered_customer_date::TIMESTAMP) AS days
        FROM olist_orders
        WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL
          AND order_purchase_timestamp IS NOT NULL
    )
    SELECT days FROM t WHERE days <= 60
    """
    raw = db.query(sql)
    rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
    if not rows:
        return "No hay datos para graficar."
    days = [float(r.get("days", 0)) for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4))
    try:
        import seaborn as sns
        sns.histplot(days, bins=30, kde=True, ax=ax, color="teal", alpha=0.7)
    except ImportError:
        ax.hist(days, bins=30, color="teal", alpha=0.7, edgecolor="white")
    ax.set_xlabel("Días de entrega")
    ax.set_ylabel("Cantidad de pedidos")
    ax.set_title("Distribución de días de entrega (hasta 60 días)")
    fig.tight_layout()
    out = _ensure_save_dir(save_dir) / filename
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return f"Gráfica guardada: {out}"


def plot_sales_by_month(
    db: Any,
    save_dir: str = "output",
    year: Optional[int] = None,
    filename: str = "ventas_por_mes.png",
) -> str:
    """Gráfico de barras: ventas por mes (opcionalmente filtrado por año)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: instala matplotlib (pip install matplotlib)"
    from duckclaw.bi.olist import get_sales_by_month
    data = _get_data(db, get_sales_by_month, year=year)
    if not data:
        return "No hay datos para graficar."
    labels = [d.get("month", "N/A") for d in data]
    values = [float(d.get("total_sales", 0)) for d in data]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(range(len(labels)), values, color="steelblue", alpha=0.85)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Ventas totales")
    ax.set_xlabel("Mes")
    title = f"Ventas por mes ({year})" if year else "Ventas por mes"
    ax.set_title(title)
    fig.tight_layout()
    out = _ensure_save_dir(save_dir) / filename
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return f"Gráfica guardada: {out}"


def plot_sales_by_month_line(
    db: Any,
    save_dir: str = "output",
    year: Optional[int] = None,
    filename: str = "ventas_por_mes_lineas.png",
) -> str:
    """Gráfico de líneas: evolución de ventas por mes (opcionalmente filtrado por año)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: instala matplotlib (pip install matplotlib)"
    from duckclaw.bi.olist import get_sales_by_month
    data = _get_data(db, get_sales_by_month, year=year)
    if not data:
        return "No hay datos para graficar."
    labels = [d.get("month", "N/A") for d in data]
    values = [float(d.get("total_sales", 0)) for d in data]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(range(len(labels)), values, marker="o", linestyle="-", color="steelblue", linewidth=2, markersize=6)
    ax.fill_between(range(len(labels)), values, alpha=0.2, color="steelblue")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Ventas totales")
    ax.set_xlabel("Mes")
    title = f"Evolución de ventas por mes ({year})" if year else "Evolución de ventas por mes"
    ax.set_title(title)
    ax.grid(True, linestyle="--", alpha=0.7)
    fig.tight_layout()
    out = _ensure_save_dir(save_dir) / filename
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return f"Gráfica guardada: {out}"


def plot_sales_vs_reviews_scatter(
    db: Any,
    save_dir: str = "output",
    sample_size: int = 1500,
    filename: str = "ventas_vs_reviews_scatter.png",
) -> str:
    """Gráfico de dispersión: valor del pedido (ventas) vs puntuación de review."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: instala matplotlib (pip install matplotlib)"
    import json
    sql = f"""
    SELECT
        ROUND((oi.total_sales)::DECIMAL(12,2), 2) AS order_sales,
        r.review_score
    FROM (
        SELECT order_id, SUM(price + freight_value) AS total_sales
        FROM olist_order_items
        GROUP BY order_id
    ) oi
    JOIN olist_orders o ON o.order_id = oi.order_id AND o.order_status = 'delivered'
    JOIN olist_order_reviews r ON r.order_id = oi.order_id
    ORDER BY random()
    LIMIT {int(sample_size)}
    """
    raw = db.query(sql)
    rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
    if not rows:
        return "No hay datos para graficar."
    x_vals = [float(r.get("order_sales", 0)) for r in rows]
    y_vals = [int(r.get("review_score", 0)) for r in rows]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(x_vals, y_vals, alpha=0.5, s=15, c="steelblue", edgecolors="none")
    ax.set_xlabel("Valor del pedido (R$)")
    ax.set_ylabel("Puntuación del review (1-5)")
    ax.set_title("Dispersión: ventas del pedido vs puntuación de review")
    ax.set_ylim(0.5, 5.5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    out = Path(save_dir).resolve() / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120, bbox_inches="tight", format="png")
    plt.close(fig)
    if out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        raise RuntimeError("savefig produjo archivo vacío")
    return f"Gráfica guardada: {out}"


def plot_from_sql(
    db: Any,
    sql: str,
    chart_type: str,
    save_dir: str = "output",
    x_label: str = "",
    y_label: str = "",
    title: str = "",
    sample_size: int = 2000,
) -> str:
    """
    Gráfico genérico desde SQL. chart_type: scatter, bar, line, pie, histogram.
    SQL debe devolver 2 columnas (x, y) para scatter/line/bar, o 1 columna para histogram.
    Solo SELECT permitido. LIMIT recomendado (máx ~5000 para scatter).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: instala matplotlib (pip install matplotlib)"
    sql_upper = (sql or "").strip().upper()
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return "Error: solo se permiten consultas SELECT o WITH."
    for blocked in ("DROP", "INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "TRUNCATE"):
        if blocked in sql_upper:
            return f"Error: no se permite {blocked} en la consulta."
    try:
        raw = db.query(sql)
        rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception as e:
        return f"Error ejecutando SQL: {e}"
    if not rows:
        return "No hay datos para graficar."
    cols = list(rows[0].keys()) if rows else []
    if len(cols) < 1:
        return "La consulta debe devolver al menos 1 columna."
    col_x, col_y = cols[0], (cols[1] if len(cols) > 1 else None)
    col_z = cols[2] if len(cols) > 2 else None
    chart_type = (chart_type or "scatter").strip().lower()

    def _to_float(v: Any) -> float:
        try:
            return float(v) if v is not None else 0.0
        except (ValueError, TypeError):
            return 0.0

    def _to_str(v: Any) -> str:
        return str(v)[:30] if v is not None else ""

    sig = hashlib.md5(sql.encode()).hexdigest()[:8]
    filename = f"plot_{chart_type}_{sig}.png"
    out_dir = Path(save_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / filename

    if chart_type == "scatter":
        if not col_y:
            return "Scatter requiere 2 columnas numéricas (eje X, eje Y)."
        data = rows[:sample_size]
        x_vals = [_to_float(r.get(col_x, 0)) for r in data]
        y_vals = [_to_float(r.get(col_y, 0)) for r in data]
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.scatter(x_vals, y_vals, alpha=0.5, s=15, c="steelblue", edgecolors="none")
        ax.set_xlabel(x_label or col_x)
        ax.set_ylabel(y_label or col_y)
        ax.set_title(title or f"Dispersión: {col_x} vs {col_y}")
        ax.grid(True, linestyle="--", alpha=0.5)
    elif chart_type == "line":
        if not col_y:
            return "Gráfico de líneas requiere 2 columnas (eje X, eje Y)."
        x_vals = [_to_str(r.get(col_x, "")) for r in rows]
        y_vals = [_to_float(r.get(col_y, 0)) for r in rows]
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(range(len(x_vals)), y_vals, marker="o", linestyle="-", color="steelblue", linewidth=2, markersize=5)
        ax.set_xticks(range(len(x_vals)))
        ax.set_xticklabels(x_vals, rotation=45, ha="right", fontsize=8)
        ax.set_xlabel(x_label or col_x)
        ax.set_ylabel(y_label or col_y)
        ax.set_title(title or f"Líneas: {col_x} vs {col_y}")
        ax.grid(True, linestyle="--", alpha=0.7)
    elif chart_type == "bar":
        labels = [_to_str(r.get(col_x, ""))[:25] for r in rows]
        vals = [_to_float(r.get(col_y, 0)) for r in rows] if col_y else [_to_float(r.get(col_x, 0)) for r in rows]
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.barh(range(len(labels)), vals, color="steelblue", alpha=0.85)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=9)
        ax.set_xlabel(y_label or (col_y or col_x))
        ax.set_title(title or f"Barras: {col_x}")
    elif chart_type == "pie":
        labels = [_to_str(r.get(col_x, ""))[:20] for r in rows]
        vals = [_to_float(r.get(col_y, 0)) for r in rows] if col_y else [_to_float(r.get(col_x, 0)) for r in rows]
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.pie(vals, labels=labels, autopct="%1.1f%%", startangle=90, colors=plt.cm.Set3.colors[: len(labels)])
        ax.set_title(title or f"Torta: {col_x}")
    elif chart_type == "histogram":
        vals = [_to_float(r.get(col_x, 0)) for r in rows]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.hist(vals, bins=min(40, len(set(vals)) or 20), color="teal", alpha=0.7, edgecolor="white")
        ax.set_xlabel(x_label or col_x)
        ax.set_ylabel("Frecuencia")
        ax.set_title(title or f"Histograma: {col_x}")
    elif chart_type == "heatmap":
        if not col_z:
            return "Heatmap requiere 3 columnas: eje X (categórico), eje Y (categórico), valor (numérico). Ej: categoría, mes, ventas."
        x_vals = [_to_str(r.get(col_x, ""))[:20] for r in rows]
        y_vals = [_to_str(r.get(col_y, ""))[:20] for r in rows]
        z_vals = [_to_float(r.get(col_z, 0)) for r in rows]
        x_unique = list(dict.fromkeys(x_vals))
        y_unique = list(dict.fromkeys(y_vals))
        if len(x_unique) > 25 or len(y_unique) > 25:
            return "Heatmap: reduce categorías (máx ~25 por eje). Usa TOP N o LIMIT en el SQL."
        grid = [[0.0] * len(x_unique) for _ in range(len(y_unique))]
        x_idx = {v: i for i, v in enumerate(x_unique)}
        y_idx = {v: i for i, v in enumerate(y_unique)}
        for xv, yv, zv in zip(x_vals, y_vals, z_vals):
            if xv in x_idx and yv in y_idx:
                grid[y_idx[yv]][x_idx[xv]] += zv
        fig, ax = plt.subplots(figsize=(max(8, len(x_unique) * 0.5), max(5, len(y_unique) * 0.4)))
        try:
            import numpy as np
            grid_arr = np.array(grid, dtype=float)
        except ImportError:
            grid_arr = grid
        im = ax.imshow(grid_arr, aspect="auto", cmap="YlOrRd")
        ax.set_xticks(range(len(x_unique)))
        ax.set_xticklabels(x_unique, rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(len(y_unique)))
        ax.set_yticklabels(y_unique, fontsize=8)
        ax.set_xlabel(x_label or col_x)
        ax.set_ylabel(y_label or col_y)
        ax.set_title(title or f"Heatmap: {col_x} × {col_y} → {col_z}")
        plt.colorbar(im, ax=ax, label=col_z)
    else:
        return f"chart_type debe ser: scatter, line, bar, pie, histogram o heatmap. Recibido: {chart_type}"

    fig.tight_layout()
    fig.savefig(out, dpi=120, bbox_inches="tight", format="png")
    plt.close(fig)
    if out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        raise RuntimeError("savefig produjo archivo vacío")
    return f"Gráfica guardada: {out}"


def plot_top_customers_bar(
    db: Any,
    save_dir: str = "output",
    limit: int = 10,
    filename: str = "top_clientes_ventas.png",
) -> str:
    """Gráfico de barras: clientes que más ventas generan (matplotlib)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "Error: instala matplotlib (pip install matplotlib)"
    from duckclaw.bi.olist import get_top_customers_by_sales
    data = _get_data(db, get_top_customers_by_sales, limit=limit)
    if not data:
        return "No hay datos para graficar."
    labels = [f"{d.get('customer_city','')} ({d.get('customer_state','')})" for d in data]
    values = [float(d.get("total_sales", 0)) for d in data]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(range(len(labels)), values, color="mediumseagreen", alpha=0.85)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Ventas totales")
    ax.set_title("Clientes que más ventas generan")
    fig.tight_layout()
    out = _ensure_save_dir(save_dir) / filename
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return f"Gráfica guardada: {out}"

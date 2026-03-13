"""
Agente BI Olist: LLM (p. ej. Groq) interpreta preguntas en lenguaje natural
y usa las funciones DuckClaw de duckclaw.bi.olist como tools.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from duckclaw.bi import olist as bi_olist


def _result_to_str(data: list[dict[str, Any]]) -> str:
    """Serializa resultado de una función BI para el LLM."""
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def build_olist_bi_tools(db: Any) -> list[Any]:
    """Construye herramientas LangChain para las funciones BI Olist (DuckClaw)."""
    from langchain_core.tools import StructuredTool

    def _safe(fn: Any, *args: Any, **kwargs: Any) -> str:
        """Evita que una falla SQL rompa el grafo; devuelve error legible."""
        try:
            data = fn(*args, **kwargs)
            return _result_to_str(data)
        except Exception as e:
            return f"Error ejecutando herramienta BI: {e}"

    def top_customers(limit: int = 15) -> str:
        """Clientes que más generan ventas. Argumento: limit (número de clientes, ej. 15)."""
        return _safe(bi_olist.get_top_customers_by_sales, db, limit=limit)

    def customers_to_retain(limit: int = 15, min_orders: int = 2) -> str:
        """Clientes a fidelizar (recurrentes, varios pedidos). Argumentos: limit, min_orders (mínimo de pedidos)."""
        return _safe(
            bi_olist.get_customers_to_retain, db, limit=limit, min_orders=min_orders
        )

    def top_sellers(limit: int = 15) -> str:
        """Mejores vendedores por ventas. Argumento: limit."""
        return _safe(bi_olist.get_top_sellers, db, limit=limit)

    def delivery_metrics() -> str:
        """Promedio y min/max de días de entrega (pedidos entregados)."""
        return _safe(bi_olist.get_delivery_metrics, db)

    def delivery_critical(days_threshold: int = 20, limit: int = 30) -> str:
        """Entregas críticas (más de X días). Argumentos: days_threshold (ej. 20), limit."""
        return _safe(
            bi_olist.get_delivery_critical_cases,
            db,
            days_threshold=days_threshold,
            limit=limit,
        )

    def sales_summary() -> str:
        """Resumen de ventas: total pedidos, ventas totales, ticket promedio."""
        return _safe(bi_olist.get_sales_summary, db)

    def review_metrics() -> str:
        """Métricas de satisfacción: puntuación media y buenas/malas reviews."""
        return _safe(bi_olist.get_review_metrics, db)

    def category_sales(limit: int = 15) -> str:
        """Ventas por categoría de producto. Argumento: limit."""
        return _safe(bi_olist.get_category_sales, db, limit=limit)

    def list_tables() -> str:
        """Lista las tablas disponibles en la base de datos. Usar cuando pregunten qué tablas hay, esquema, o estructura de la DB."""
        return _safe(bi_olist.list_tables, db)

    def describe_table(table_name: str) -> str:
        """Describe las columnas de una tabla. Usar antes de plot_query para saber qué columnas usar. table_name: ej. olist_order_items, olist_orders."""
        return _safe(bi_olist.describe_table, db, table_name)

    def sales_by_month(year: Optional[int] = None, limit: int = 24) -> str:
        """Ventas totales por mes (pedidos entregados). year: filtrar por año (ej. 2018). limit: máximo de meses."""
        return _safe(bi_olist.get_sales_by_month, db, year=year, limit=limit)

    # Herramientas de gráficas (matplotlib/seaborn)
    try:
        from duckclaw.bi import plots as bi_plots
        from pathlib import Path
        # Ruta absoluta al output (no depender de cwd; el bot puede arrancar desde otro dir)
        _project_root = Path(__file__).resolve().parent.parent.parent
        _out = (_project_root / "output").resolve()
        _out.mkdir(parents=True, exist_ok=True)
        _save = str(_out)

        def plot_categories(limit: int = 12) -> str:
            """Genera gráfico de BARRAS de ventas por categoría. Solo para barras; si piden torta usar plot_category_sales_pie."""
            return bi_plots.plot_category_sales_bar(db, save_dir=_save, limit=limit)

        def plot_categories_pie(limit: int = 5) -> str:
            """Genera diagrama de TORTA (pie chart) de top categorías por ventas. Usar cuando pidan torta, pie, circular de categorías."""
            return bi_plots.plot_category_sales_pie(db, save_dir=_save, limit=limit)

        def plot_sellers(limit: int = 10) -> str:
            """Genera gráfico de barras de mejores vendedores. Usar cuando pidan gráfica de vendedores."""
            return bi_plots.plot_top_sellers_bar(db, save_dir=_save, limit=limit)

        def plot_reviews_pie() -> str:
            """Genera gráfico de torta de puntuaciones de reviews. Usar cuando pidan gráfica de valoraciones o satisfacción."""
            return bi_plots.plot_review_score_pie(db, save_dir=_save)

        def plot_delivery_hist() -> str:
            """Genera histograma de días de entrega. Usar cuando pidan gráfica de tiempos de entrega."""
            return bi_plots.plot_delivery_days_histogram(db, save_dir=_save)

        def plot_customers_bar(limit: int = 10) -> str:
            """Genera gráfico de barras de clientes que más ventas generan. Usar cuando pidan gráfica de clientes top."""
            return bi_plots.plot_top_customers_bar(db, save_dir=_save, limit=limit)

        def plot_sales_by_month(year: Optional[int] = None) -> str:
            """Genera gráfico de BARRAS de ventas por mes. year: filtrar por año (ej. 2018). Usar SOLO cuando pidan barras. Si piden líneas → plot_sales_by_month_line."""
            return bi_plots.plot_sales_by_month(db, save_dir=_save, year=year)

        def plot_sales_by_month_line(year: Optional[int] = None) -> str:
            """Genera gráfico de LÍNEAS de ventas por mes. year: filtrar por año (ej. 2017). Usar cuando pidan gráfico de líneas, evolución, tendencia o ventas por mes en formato línea."""
            return bi_plots.plot_sales_by_month_line(db, save_dir=_save, year=year)

        def plot_sales_vs_reviews_scatter(sample_size: int = 3000) -> str:
            """Genera gráfico de DISPERSIÓN: valor del pedido (ventas) vs puntuación del review. Usar cuando pidan scatter, dispersión o correlación ventas-reviews."""
            return bi_plots.plot_sales_vs_reviews_scatter(db, save_dir=_save, sample_size=sample_size)

        def plot_query(
            sql: str,
            chart_type: str,
            x_label: str = "",
            y_label: str = "",
            title: str = "",
            sample_size: int = 2000,
        ) -> str:
            """Genera CUALQUIER gráfico desde una consulta SQL. chart_type: scatter, bar, line, pie, histogram, heatmap. SQL: 2 cols (x,y) para scatter/line/bar, 1 para histogram, 3 cols (x,y,valor) para heatmap. Usar describe_table antes si no conoces columnas. Incluir LIMIT (ej. 2000)."""
            return bi_plots.plot_from_sql(
                db, sql, chart_type, save_dir=_save,
                x_label=x_label, y_label=y_label, title=title, sample_size=sample_size,
            )

        def export_to_excel(
            sql: str,
            sheet_name: str = "Datos",
            limit: int = 10000,
        ) -> str:
            """Exporta el resultado de una consulta SQL a un archivo Excel (.xlsx) descargable. sql: consulta SELECT. sheet_name: nombre de la hoja. limit: máximo de filas (ej. 10000). Usar cuando pidan Excel, exportar, descargar datos, hoja de cálculo."""
            from duckclaw.bi import excel_export
            return excel_export.export_query_to_excel(
                db, sql, save_dir=_save, sheet_name=sheet_name, limit=limit,
            )

        def create_report_markdown(
            filename: str,
            title: str,
            insights: str,
            summary_data: Optional[list] = None,
            image_refs: Optional[list] = None,
        ) -> str:
            """Crea un INFORME en Markdown con insights y análisis. NO usar para tablas crudas (usar export_to_excel).
            filename: nombre descriptivo sin extensión (ej. ventas_noviembre_2017, kpis_nov_2017).
            title: título del informe.
            insights: análisis, conclusiones, hallazgos en markdown.
            summary_data: opcional, lista de dicts para tabla resumen (máx 10 filas).
            image_refs: opcional, nombres de gráficas en output/ (ej. ventas_por_mes.png).
            Usar cuando pidan reporte, informe, insights en MD. Primero obtener datos con get_* y/o plot_*, luego generar insights y llamar esta herramienta."""
            from duckclaw.bi import markdown_export
            return markdown_export.create_report_markdown(
                save_dir=_save,
                filename=filename,
                title=title,
                insights=insights,
                summary_data=summary_data,
                image_refs=image_refs,
            )

        plot_tools = [
            StructuredTool.from_function(
                func=plot_categories,
                name="plot_category_sales_bar",
                description="Genera gráfico de BARRAS de ventas por categoría. Usar SOLO cuando pidan explícitamente barras. Si piden torta, pie o circular → usar plot_category_sales_pie.",
            ),
            StructuredTool.from_function(
                func=plot_categories_pie,
                name="plot_category_sales_pie",
                description="Genera diagrama de TORTA (pie chart) con el top de categorías por ventas. Usar cuando pidan torta, pie chart, gráfico circular o diagrama circular de categorías/ventas.",
            ),
            StructuredTool.from_function(
                func=plot_sellers,
                name="plot_top_sellers_bar",
                description="Genera y guarda un gráfico de barras de mejores vendedores. Usar cuando pidan gráfica de vendedores.",
            ),
            StructuredTool.from_function(
                func=plot_reviews_pie,
                name="plot_review_score_pie",
                description="Genera y guarda un gráfico de torta de puntuaciones de reviews. Usar cuando pidan gráfica de valoraciones o satisfacción.",
            ),
            StructuredTool.from_function(
                func=plot_delivery_hist,
                name="plot_delivery_days_histogram",
                description="Genera y guarda un histograma de días de entrega. Usar cuando pidan gráfica de tiempos o plazos de entrega.",
            ),
            StructuredTool.from_function(
                func=plot_customers_bar,
                name="plot_top_customers_bar",
                description="Genera y guarda un gráfico de barras de clientes que más ventas generan. Usar cuando pidan gráfica de clientes top.",
            ),
            StructuredTool.from_function(
                func=plot_sales_by_month,
                name="plot_sales_by_month",
                description="Genera gráfico de BARRAS de ventas por mes. year (ej. 2018). Usar SOLO cuando pidan barras. Si piden líneas → plot_sales_by_month_line.",
            ),
            StructuredTool.from_function(
                func=plot_sales_by_month_line,
                name="plot_sales_by_month_line",
                description="Genera gráfico de LÍNEAS de ventas por mes. year (ej. 2017). Usar cuando pidan gráfico de líneas, evolución, tendencia o ventas por mes en formato línea.",
            ),
            StructuredTool.from_function(
                func=plot_sales_vs_reviews_scatter,
                name="plot_sales_vs_reviews_scatter",
                description="Genera gráfico de DISPERSIÓN (scatter): valor del pedido vs puntuación del review. Usar cuando pidan scatter, dispersión o correlación ventas-reviews.",
            ),
            StructuredTool.from_function(
                func=plot_query,
                name="plot_query",
                description="Genera CUALQUIER gráfico desde SQL. chart_type: scatter, bar, line, pie, histogram, heatmap. heatmap: 3 columnas (eje X, eje Y, valor). Ej: categoría, mes, ventas. scatter/line/bar: 2 cols. histogram: 1 col. Usar describe_table. Incluir LIMIT (ej. 2000).",
            ),
            StructuredTool.from_function(
                func=export_to_excel,
                name="export_to_excel",
                description="SOLO para tablas crudas cuando pidan EXPLÍCITAMENTE Excel. NUNCA si piden reporte/informe/insights en MD.",
            ),
            StructuredTool.from_function(
                func=create_report_markdown,
                name="create_report_markdown",
                description="Reporte/informe en MD. UN SOLO archivo. filename: ventas_noviembre_2017, kpis_nov_2017. insights: TODO el análisis (va DENTRO del MD, no en mensaje). summary_data: resumen breve. image_refs: gráficas. NUNCA export_to_excel para reportes.",
            ),
        ]
    except Exception:
        plot_tools = []

    return [
        StructuredTool.from_function(
            func=top_customers,
            name="get_top_customers_by_sales",
            description="Lista los clientes que más ventas generan (por valor total). Usar cuando pregunten quiénes son los mejores clientes, quiénes más compran, o clientes top por ventas.",
        ),
        StructuredTool.from_function(
            func=customers_to_retain,
            name="get_customers_to_retain",
            description="Clientes candidatos a fidelizar: con varios pedidos y buen valor. Usar para fidelización, clientes recurrentes, a quiénes retener.",
        ),
        StructuredTool.from_function(
            func=top_sellers,
            name="get_top_sellers",
            description="Mejores vendedores por valor vendido. Usar para mejores vendedores, ranking de sellers.",
        ),
        StructuredTool.from_function(
            func=delivery_metrics,
            name="get_delivery_metrics",
            description="Promedio, mínimo y máximo de días de entrega. Usar para tiempo de entrega promedio, plazos de entrega.",
        ),
        StructuredTool.from_function(
            func=delivery_critical,
            name="get_delivery_critical_cases",
            description="Pedidos con entrega muy tardía (más de X días). Usar para casos críticos, entregas atrasadas, retrasos.",
        ),
        StructuredTool.from_function(
            func=sales_summary,
            name="get_sales_summary",
            description="Resumen ejecutivo: total pedidos, ventas totales, ticket promedio. Usar para resumen de ventas, KPIs globales.",
        ),
        StructuredTool.from_function(
            func=review_metrics,
            name="get_review_metrics",
            description="Satisfacción: nota media y cantidad de reviews buenas/malas. Usar para valoraciones, satisfacción, reviews.",
        ),
        StructuredTool.from_function(
            func=category_sales,
            name="get_category_sales",
            description="Ventas por categoría de producto. Usar para categorías más vendidas, ventas por tipo de producto.",
        ),
        StructuredTool.from_function(
            func=list_tables,
            name="list_tables",
            description="Lista las tablas disponibles en la base de datos. Usar cuando pregunten qué tablas hay, esquema, estructura de la DB o tablas disponibles.",
        ),
        StructuredTool.from_function(
            func=describe_table,
            name="describe_table",
            description="Describe las columnas de una tabla. Usar antes de plot_query para saber qué columnas usar. table_name: ej. olist_order_items, olist_orders.",
        ),
        StructuredTool.from_function(
            func=sales_by_month,
            name="get_sales_by_month",
            description="Ventas totales por mes (pedidos entregados). Argumento year (ej. 2018) para filtrar. Usar para evolución mensual, ventas por mes.",
        ),
    ] + plot_tools


# Tools permitidos en el datalake Olist (para validación)
OLIST_BI_TOOL_NAMES = frozenset({
    "get_top_customers_by_sales", "get_customers_to_retain", "get_top_sellers",
    "get_delivery_metrics", "get_delivery_critical_cases", "get_sales_summary",
    "get_review_metrics", "get_category_sales", "list_tables", "describe_table", "get_sales_by_month",
    "plot_category_sales_bar", "plot_category_sales_pie", "plot_top_sellers_bar", "plot_review_score_pie",
    "plot_delivery_days_histogram", "plot_top_customers_bar", "plot_sales_by_month",
    "plot_sales_by_month_line", "plot_sales_vs_reviews_scatter", "plot_query",
    "export_to_excel", "create_report_markdown",
})

SYSTEM_PROMPT_BI = """Eres un analista BI para una tienda online (dataset Olist). Respondes en español.

Tienes herramientas de datos (get_*) y de gráficas (plot_*). Las gráficas se guardan en "output"; indica la ruta del archivo generado.

## Formato de respuesta obligatorio

Siempre responde con estas tres etiquetas en orden. Cierra todas las etiquetas.

<thought>
1. Análisis del contexto (pregunta del usuario).
2. Identificación de la necesidad (datos o gráfica).
3. Decisión de la herramienta a utilizar.
</thought>
<tool_call>
{"tool": "nombre_herramienta", "args": {"param": valor, ...}}
</tool_call>
<answer>
La respuesta final en lenguaje natural para el usuario o el reporte de la acción ejecutada.
</answer>

## Reglas
- Sé conciso: máximo 3-4 puntos clave en el análisis. No incluyas rutas de archivos. Evita respuestas largas que se trunquen.
- El contenido de <tool_call> debe ser JSON válido parseable por Python (json.loads).
- Si piden varias cosas, incluye un JSON por línea dentro de <tool_call>; el sistema ejecutará cada uno y devolverá la respuesta en lenguaje natural.
- Tools de datos: get_top_customers_by_sales, get_customers_to_retain, get_top_sellers, get_delivery_metrics, get_delivery_critical_cases, get_sales_summary, get_review_metrics, get_category_sales, list_tables, get_sales_by_month.
- Tools de gráficas: plot_category_sales_bar, plot_category_sales_pie (diagrama de torta), plot_top_sellers_bar, plot_review_score_pie, plot_delivery_days_histogram, plot_top_customers_bar, plot_sales_by_month.
- Argumentos típicos: limit (int), min_orders (int), days_threshold (int), year (int, ej. 2018 para ventas por mes).
- IMPORTANTE: Si piden diagrama de torta, pie chart o gráfico circular de categorías por ventas → usar plot_category_sales_pie (NO plot_category_sales_bar). plot_category_sales_bar es solo para gráficos de barras.

## Ejemplos Olist

[USUARIO]: ¿Quiénes son los mejores vendedores?
<thought>
1. Análisis: El usuario pide los mejores vendedores.
2. Necesidad: Datos de ranking de sellers por ventas.
3. Herramienta: get_top_sellers con limit por defecto.
</thought>
<tool_call>
{"tool": "get_top_sellers", "args": {"limit": 10}}
</tool_call>
<answer>
Consultando los mejores vendedores por ventas...
</answer>

[USUARIO]: ¿Cuál es el tiempo medio de entrega?
<thought>
1. Análisis: Pregunta sobre plazos de entrega.
2. Necesidad: Métricas de días de entrega (promedio, min, max).
3. Herramienta: get_delivery_metrics.
</thought>
<tool_call>
{"tool": "get_delivery_metrics", "args": {}}
</tool_call>
<answer>
Obteniendo métricas de entrega...
</answer>

[USUARIO]: ¿Mejores vendedores y tiempo medio de entrega?
<thought>
1. Análisis: El usuario pide dos cosas: ranking de vendedores y métricas de entrega.
2. Necesidad: get_top_sellers y get_delivery_metrics.
3. Herramientas: ambas en el mismo turno.
</thought>
<tool_call>
{"tool": "get_top_sellers", "args": {"limit": 10}}
{"tool": "get_delivery_metrics", "args": {}}
</tool_call>
<answer>
Consultando vendedores y métricas de entrega...
</answer>

[USUARIO]: Gráfico de barras de los clientes que más compran
<thought>
1. Análisis: Piden visualización de clientes top.
2. Necesidad: Gráfico de barras de clientes por ventas.
3. Herramienta: plot_top_customers_bar.
</thought>
<tool_call>
{"tool": "plot_top_customers_bar", "args": {"limit": 10}}
</tool_call>
<answer>
Generando gráfico de clientes top...
</answer>

[USUARIO]: Haz un diagrama de torta con las top 5 categorías por venta
<thought>
1. Análisis: Piden diagrama de torta (pie chart) de categorías por ventas.
2. Necesidad: Gráfico circular/torta de top categorías.
3. Herramienta: plot_category_sales_pie (diagrama de torta de categorías).
</thought>
<tool_call>
{"tool": "plot_category_sales_pie", "args": {"limit": 5}}
</tool_call>
<answer>
Generando diagrama de torta con las top 5 categorías por venta...
</answer>

[USUARIO]: ¿Qué tablas hay disponibles?
<thought>
1. Análisis: El usuario pregunta qué tablas existen en la base.
2. Necesidad: Listar las tablas disponibles.
3. Herramienta: list_tables.
</thought>
<tool_call>
{"tool": "list_tables", "args": {}}
</tool_call>
<answer>
Consultando las tablas disponibles...
</answer>

[USUARIO]: Haz una gráfica de ventas por mes en 2018
<thought>
1. Análisis: Piden gráfica de ventas por mes, filtrada por año 2018.
2. Necesidad: Gráfico de barras de ventas mensuales.
3. Herramienta: plot_sales_by_month con year=2018.
</thought>
<tool_call>
{"tool": "plot_sales_by_month", "args": {"year": 2018}}
</tool_call>
<answer>
Generando gráfica de ventas por mes en 2018...
</answer>
"""

# Prompt para modelos con tool-calling nativo (OpenAI, DeepSeek, etc.).
# Sin formato <tool_call> para evitar confusión: el modelo usa la API nativa.
SYSTEM_PROMPT_BI_NATIVE = """Eres un analista BI para una tienda online (dataset Olist). Respondes en español.

Tienes herramientas de datos (get_*) y de gráficas (plot_*). SIEMPRE usa las herramientas para responder preguntas de datos. Nunca respondas sin consultar primero.

Herramientas:
- list_tables: qué tablas hay (para "cuántas tablas", "qué tablas", "esquema")
- describe_table: columnas de una tabla (usar antes de plot_query si no conoces las columnas)
- get_top_sellers: mejores vendedores por ventas
- get_delivery_metrics: promedio, min, max de días de entrega
- get_delivery_critical_cases: entregas tardías (days_threshold, limit)
- get_sales_summary: resumen ventas (pedidos, total, ticket medio)
- get_category_sales: ventas por categoría
- get_top_customers_by_sales: clientes que más compran
- get_sales_by_month: ventas por mes (year opcional)
- plot_*: gráficas (barras, torta, histograma, líneas)
- plot_sales_by_month_line: gráfico de LÍNEAS de ventas por mes (year opcional). Usar cuando pidan "gráfico de líneas", "evolución" o "tendencia".
- plot_sales_vs_reviews_scatter: gráfico de DISPERSIÓN (scatter) ventas vs reviews. Usar cuando pidan "scatter", "dispersión" o "ventas contra reviews".
- plot_query: CUALQUIER gráfico desde SQL. chart_type: scatter, bar, line, pie, histogram, heatmap. Usar cuando pidan heatmap, mapa de calor, matriz.
- export_to_excel: SOLO para tablas crudas cuando pidan EXPLÍCITAMENTE Excel. NUNCA usar si piden reporte, informe o insights en MD.
- create_report_markdown: para reportes/informes en MD. UN SOLO archivo. filename DESCRIPTIVO: ventas_noviembre_2017, kpis_nov_2017. insights: TODO el análisis va aquí (no en el mensaje). summary_data: tabla resumen breve (máx 5 filas). image_refs: gráficas si plot_* se usó. Flujo: 1) get_* y plot_* para datos, 2) create_report_markdown UNA VEZ con insights completos.

Reglas:
- Si piden "exportar a excel", "exporta a excel", "en excel": usar SOLO export_to_excel. NO usar plot_*, NO usar create_report_markdown.
- Sé conciso: máximo 3-4 puntos clave en análisis. No incluyas rutas de archivos. Evita respuestas largas que se trunquen.
- Para "cuántas tablas" o "qué tablas hay" → list_tables
- Para gráficos con columnas no predefinidas (precio vs flete, ventas vs pedidos por vendedor, etc.) → describe_table + plot_query
- Para "vendedor con más ventas" o "mejores vendedores" → get_top_sellers
- Para "promedio de entrega" o "tiempo de entrega" → get_delivery_metrics
- Para "casos críticos" de entrega → get_delivery_critical_cases
- Responde con los datos obtenidos de forma clara. No inventes ni preguntes al usuario.
"""


import re


def _strip_artifacts(text: str) -> str:
    """Elimina sufijos como <|eom_id|>, <|eot_id|> y espacios sobrantes."""
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r"<\|eom_id\|>\s*", "", t)
    t = re.sub(r"<\|eot_id\|>\s*", "", t)
    return t.strip()


def _extract_json_objects(text: str) -> list[str]:
    """Extrae subcadenas que son objetos JSON válidos {...} con anidamiento."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] != "{":
            i += 1
            continue
        start = i
        depth = 0
        for j in range(i, len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[start : j + 1])
                    i = j + 1
                    break
        else:
            i += 1
    return out


def _parse_raw_tool_calls(text: str) -> list[dict[str, Any]]:
    """
    Parsea tool-calls crudos en texto. Soporta:
    - {"tool": "x", "args": {...}}
    - {"name": "x", "parameters": {...}}
    - Múltiples objetos separados por ; o newlines
    """
    text = _strip_artifacts(text)
    out: list[dict[str, Any]] = []
    for raw in _extract_json_objects(text):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        tool = obj.get("tool") or obj.get("name")
        args = obj.get("args") or obj.get("parameters") or {}
        if not tool or tool not in OLIST_BI_TOOL_NAMES:
            continue
        coerced: dict[str, Any] = {}
        for k, v in args.items():
            if isinstance(v, str) and v.isdigit():
                coerced[k] = int(v)
            else:
                coerced[k] = v
        out.append({"tool": str(tool), "args": coerced})
    return out


def _is_raw_tool_calls_reply(text: str) -> bool:
    """Detecta si la respuesta parece tool-calls crudos en texto (sin wrapper estructurado)."""
    if not text or len(text) > 10000:
        return False
    t = _strip_artifacts(text)
    # Si tiene formato estructurado completo, no es "raw"
    if "<thought>" in t and "<tool_call>" in t and "<answer>" in t:
        return False
    # Patrón: {"name": ... o {"tool": ...
    if re.search(r'\{"(?:name|tool)"\s*:\s*"[^"]+",\s*"(?:parameters|args)"', t):
        return True
    # Múltiples objetos con ;
    if "};" in t and '"name"' in t:
        return True
    return False


def _fmt(val: Any) -> str:
    """Formatea valor para display (evita errores con :, en números)."""
    if val is None:
        return "?"
    s = str(val)
    try:
        f = float(s.replace(",", "."))
        return f"{f:,.1f}" if f != int(f) else f"{int(f):,}"
    except (ValueError, TypeError):
        return s


def _result_to_natural_language(tool_name: str, raw: str) -> str:
    """Convierte el resultado de una tool en lenguaje natural."""
    raw = (raw or "").strip()
    if "output/" in raw or raw.endswith(".png"):
        return f"Gráfica generada y guardada en: {raw}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:800] if len(raw) > 800 else raw
    if isinstance(data, list):
        if not data:
            return "No hay datos."
        if "get_top_sellers" in tool_name:
            items = data[:5]
            parts = [f"{i.get('seller_city', i.get('seller_id', '?'))} ({_fmt(i.get('total_sales'))})" for i in items]
            return f"Los mejores vendedores son: {', '.join(parts)}. Total: {len(data)} vendedores."
        if "get_top_customers" in tool_name:
            items = data[:5]
            parts = [f"{i.get('customer_city', '?')} ({_fmt(i.get('total_sales'))})" for i in items]
            return f"Clientes top por ventas: {', '.join(parts)}. Total: {len(data)} clientes."
        if "get_customers_to_retain" in tool_name:
            items = data[:5]
            cities = [str(i.get("customer_city", i.get("customer_id", "?"))) for i in items]
            return f"Clientes a fidelizar: {len(data)} candidatos. Ejemplos: {', '.join(cities)}."
        if "get_delivery_metrics" in tool_name:
            d = data[0] if data else {}
            avg = d.get("avg_delivery_days", d.get("avg_days", "?"))
            mn = d.get("min_delivery_days", d.get("min_days", "?"))
            mx = d.get("max_delivery_days", d.get("max_days", "?"))
            return f"Tiempo de entrega: promedio {_fmt(avg)} días (mín: {_fmt(mn)}, máx: {_fmt(mx)})."
        if "get_sales_summary" in tool_name:
            d = data[0] if data else {}
            return f"Resumen: {_fmt(d.get('total_orders'))} pedidos, ventas totales {_fmt(d.get('total_sales'))}, ticket promedio {_fmt(d.get('avg_ticket'))}."
        if "get_review_metrics" in tool_name:
            d = data[0] if data else {}
            return f"Satisfacción: nota media {_fmt(d.get('avg_score'))}, reviews buenas {_fmt(d.get('good_reviews'))}, malas {_fmt(d.get('bad_reviews'))}."
        if "get_category_sales" in tool_name:
            items = data[:5]
            parts = [f"{i.get('category', '?')} ({_fmt(i.get('total_sales'))})" for i in items]
            return f"Ventas por categoría: {', '.join(parts)}. Total: {len(data)} categorías."
        if "list_tables" in tool_name:
            tables = [t.get("table_name", "?") for t in data if isinstance(t, dict)]
            return f"Tablas disponibles: {', '.join(tables)}." if tables else "No hay tablas."
        if "get_sales_by_month" in tool_name:
            items = data[:5]
            parts = [f"{i.get('month', '?')} ({_fmt(i.get('total_sales'))})" for i in items]
            return f"Ventas por mes: {', '.join(parts)}. Total: {len(data)} meses."
        if "get_delivery_critical" in tool_name:
            return f"Hay {len(data)} casos críticos de entrega tardía."
        return f"{len(data)} registros obtenidos."
    if isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)[:500]
    return str(data)[:500]


def _execute_tool_calls_and_compose(
    db: Any,
    tools: list[Any],
    tool_calls: list[dict[str, Any]],
) -> str:
    """Ejecuta las tool-calls y compone la respuesta final en lenguaje natural."""
    by_name = {t.name: t for t in tools}
    results: list[str] = []
    for tc in tool_calls:
        name = tc.get("tool", "")
        args = tc.get("args") or {}
        if name not in by_name:
            results.append(f"Herramienta desconocida: {name}")
            continue
        try:
            out = by_name[name].invoke(args)
            results.append(_result_to_natural_language(name, out))
        except Exception as e:
            results.append(f"Error en {name}: {e}")
    if not results:
        return "No se pudieron ejecutar las herramientas."
    return "\n\n".join(results)


def _extract_tool_calls_from_structured(reply: str) -> list[dict[str, Any]]:
    """Extrae tool-calls del bloque <tool_call>...</tool_call> en formato estructurado."""
    m = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", reply, re.DOTALL)
    if not m:
        return []
    block = m.group(1).strip()
    return _parse_raw_tool_calls(block)


def _normalize_mlx_reply(reply: str, db: Any, tools: list[Any]) -> str:
    """
    Normaliza la respuesta del LLM. Si hay tool-calls (crudos o en bloque estructurado),
    los ejecuta y devuelve respuesta en lenguaje natural.
    """
    reply = _strip_artifacts(reply or "")
    if not reply:
        return "No hubo respuesta."
    # Formato estructurado: extraer tool_calls del bloque <tool_call>
    if "<tool_call>" in reply and "</tool_call>" in reply:
        parsed = _extract_tool_calls_from_structured(reply)
        if parsed:
            return _execute_tool_calls_and_compose(db, tools, parsed)
    # Tool-calls crudos (sin wrapper)
    if _is_raw_tool_calls_reply(reply):
        parsed = _parse_raw_tool_calls(reply)
        if parsed:
            return _execute_tool_calls_and_compose(db, tools, parsed)
    # Si la respuesta tiene <answer>...</answer>, extraer solo ese bloque
    m_answer = re.search(r"<answer>\s*(.*?)\s*</answer>", reply, re.DOTALL)
    if m_answer:
        return m_answer.group(1).strip()
    # Quitar <thought>...</thought> si queda solo eso (respuesta incompleta)
    reply = re.sub(r"<thought>.*?</thought>\s*", "", reply, flags=re.DOTALL)
    return reply.strip() or "No hubo respuesta."


def _last_ai_content(messages: list) -> str:
    """Extrae el contenido del último mensaje AI (no tool call)."""
    for m in reversed(messages):
        if not hasattr(m, "content") or not m.content:
            continue
        kind = getattr(m, "type", "") or getattr(m.__class__, "__name__", "")
        if kind == "ai" or "AIMessage" in str(kind):
            if not getattr(m, "tool_calls", None):
                return (m.content or "").strip()
    return ""


def build_bi_graph(
    db: Any,
    llm: Any,
    *,
    system_prompt: str = "",
    system_prompt_extra: str = "",
) -> Any:
    """
    Grafo LangGraph: pregunta del usuario → LLM con tools BI Olist → respuesta.

    Estado: incoming (str), opcional history. Salida: reply (str).
    """
    from langchain_core.messages import HumanMessage, AIMessage
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph import END, StateGraph
    from langgraph.prebuilt import create_react_agent

    tools = build_olist_bi_tools(db)
    # create_react_agent usa tool-calling nativo: prompt sin formato <tool_call>
    base = (system_prompt or SYSTEM_PROMPT_BI_NATIVE).strip()
    extra = (system_prompt_extra or "").strip()
    prompt = f"{base}\n\n{extra}" if extra else base
    # Compatible con LangGraph nuevo (prompt=) y antiguo (state_modifier=)
    try:
        agent = create_react_agent(llm, tools, prompt=prompt)
    except TypeError:
        agent = create_react_agent(llm, tools, state_modifier=prompt)

    def wrap_invoke(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        incoming = (state.get("incoming") or "").strip()
        history = state.get("history") or []
        invoke_config = config if config is not None else None
        # Construir mensajes con historial para contexto multi-turno
        prior = []
        for h in history:
            role = (h.get("role") or "").lower()
            content = (h.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                prior.append(HumanMessage(content=content))
            elif role == "assistant":
                prior.append(AIMessage(content=content))
        prior.append(HumanMessage(content=incoming))
        result = agent.invoke(
            {"messages": prior},
            config=invoke_config,
        )
        messages = result.get("messages") or []
        reply = _last_ai_content(messages)
        # Incluir salidas de tools con rutas de archivo (gráficas, Excel, MD) para que el bot las detecte
        for m in messages:
            if getattr(m, "type", "") == "tool" or "ToolMessage" in type(m).__name__:
                raw = getattr(m, "content", None)
                content = raw if isinstance(raw, str) else (raw[0].get("text", "") if isinstance(raw, list) and raw and isinstance(raw[0], dict) else str(raw or ""))
                if content and (".png" in content or ".xlsx" in content or ".md" in content):
                    reply = (reply or "") + "\n" + content
        return {"reply": reply or "No hubo respuesta."}

    graph = StateGraph(dict)
    graph.add_node("agent", wrap_invoke)
    graph.set_entry_point("agent")
    graph.add_edge("agent", END)
    return graph.compile()


def ask_bi(
    db: Any,
    question: str,
    *,
    llm: Optional[Any] = None,
    provider: str = "groq",
    model: str = "",
    save_traces: bool = False,
    send_to_langsmith: bool = False,
    system_prompt_extra: str = "",
    history: Optional[list[dict]] = None,
) -> str:
    """
    Pregunta en lenguaje natural al agente BI (una sola llamada).

    - db: DuckClaw con datos Olist ya cargados (load_olist_data).
    - question: texto en lenguaje natural.
    - llm: si se pasa, se usa este LLM; si no, se construye uno con build_llm(provider, model).
    - provider: "groq" (GROQ_API_KEY), "deepseek" (DEEPSEEK_API_KEY) o "mlx" (local).
    - model: modelo según provider (groq: llama-3.3-70b-versatile, deepseek: deepseek-chat).
    - save_traces: si True, guarda la traza XML en train/grpo_olist_traces.jsonl para GRPO.
    - send_to_langsmith: si True (y save_traces), envía la traza a LangSmith (LANGCHAIN_API_KEY).
    - system_prompt_extra: texto adicional al system prompt (ej. SKILLS.md para guiar herramientas).
    - history: lista de {"role": "user"|"assistant", "content": str} para contexto multi-turno.

    Devuelve la respuesta en texto.
    """
    # Validación rápida de tablas mínimas para evitar errores SQL opacos
    try:
        import json as _json
        _tbls = db.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' ORDER BY table_name"
        )
        _names = {r.get("table_name") for r in (_json.loads(_tbls) if isinstance(_tbls, str) else (_tbls or []))}
        _required = {"olist_orders", "olist_order_items", "olist_sellers"}
        if not _required.issubset(_names):
            return (
                "Faltan tablas Olist en la base. Ejecuta primero "
                "`load_olist_data(db, <ruta_data>)` y verifica que cargue correctamente."
            )
    except Exception:
        pass

    if llm is None:
        from duckclaw.integrations.llm_providers import build_llm
        llm = build_llm(provider, model or "")
    prompt_extra = (system_prompt_extra or "").strip()
    try:
        graph = build_bi_graph(db, llm, system_prompt_extra=prompt_extra)
        run_name = f"User: {question[:80]}{'...' if len(question) > 80 else ''}"
        try:
            from langsmith.run_helpers import trace, tracing_context
            import os as _os
            _proj = _os.environ.get("LANGCHAIN_PROJECT", "Olist")
            _do_trace = (
                send_to_langsmith
                or _os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
                or _os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
            )
            if _do_trace:
                with tracing_context(enabled=True, project_name=_proj):
                    with trace(
                        run_name,
                        run_type="chain",
                        inputs={"messages": question, "prompt": question},
                    ) as _run:
                        result = graph.invoke({"incoming": question, "history": history or []})
                        reply = result.get("reply") or ""
                        _run.end(outputs={"reply": reply})
            else:
                result = graph.invoke({"incoming": question, "history": history or []})
                reply = result.get("reply") or ""
        except ImportError:
            result = graph.invoke({"incoming": question, "history": history or []})
            reply = result.get("reply") or ""
        tools = build_olist_bi_tools(db)
        final = _normalize_mlx_reply(reply, db, tools)
        if save_traces and reply:
            try:
                from duckclaw.bi.grpo_traces import save_grpo_trace
                save_grpo_trace(
                    question,
                    reply,
                    provider=provider,
                    source="ask_bi",
                    send_to_langsmith=send_to_langsmith,
                )
            except Exception:
                pass
        return final
    except Exception as e:
        err_msg = str(e).lower()
        if "429" in err_msg or "rate limit" in err_msg or "rate_limit" in err_msg:
            return (
                "⚠️ Límite de uso de la API (Groq) alcanzado. Espera unos minutos o mejora tu plan. "
                "Mientras tanto puedes usar las funciones directas: get_top_sellers(db), get_delivery_metrics(db), "
                "plot_category_sales_bar(db), etc."
            )
        raise

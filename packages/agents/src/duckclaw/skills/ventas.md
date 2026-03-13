---
name: olist-ventas
description: Resumen de ventas, categorías y evolución mensual
allowed-tools: get_sales_summary get_category_sales get_sales_by_month plot_category_sales_bar plot_category_sales_pie plot_sales_by_month plot_sales_by_month_line plot_sales_vs_reviews_scatter plot_query describe_table create_report_markdown export_to_excel
---

# Ventas

## Cuándo activar

- "Resumen de ventas"
- "Total pedidos"
- "Ticket medio"
- "Categorías más vendidas"
- "Ventas por categoría"
- "Ventas por mes"
- "Evolución mensual"
- "Gráfico de barras categorías"
- "Diagrama de torta categorías"
- "Gráfica ventas por mes"
- "Gráfico de líneas"
- "Evolución en líneas"
- "Tendencia de ventas"
- "Gráfico de dispersión"
- "Scatter ventas reviews"

## Herramientas

- `get_sales_summary`: total pedidos, ventas, ticket promedio.
- `get_category_sales`: ventas por categoría. Args: limit (default 15).
- `get_sales_by_month`: ventas mensuales. Args: year (opcional), limit (default 24).
- `plot_category_sales_bar`: barras de categorías. Args: limit (default 12).
- `plot_category_sales_pie`: torta de categorías. Args: limit (default 5).
- `plot_sales_by_month`: barras por mes. Args: year (opcional).
- `plot_sales_by_month_line`: gráfico de LÍNEAS de ventas por mes. Args: year (opcional). Usar cuando pidan líneas, evolución o tendencia.
- `plot_sales_vs_reviews_scatter`: scatter ventas vs reviews. Usar cuando pidan dispersión, scatter o ventas contra reviews.
- `plot_query`: CUALQUIER gráfico desde SQL (scatter, bar, line, pie, histogram, heatmap). heatmap: 3 columnas (eje X, eje Y, valor). Usar cuando pidan heatmap, mapa de calor, ventas por categoría y mes, etc.
- `describe_table`: columnas de una tabla. Usar antes de plot_query.

## Reportes MD vs Excel

- **Reporte/informe MD con insights**: SOLO `create_report_markdown`. UN archivo. filename: ventas_noviembre_2017, kpis_nov_2017. insights: TODO el análisis DENTRO del MD. NUNCA export_to_excel.
- **Tablas crudas en Excel**: `export_to_excel` SOLO cuando pidan explícitamente Excel.

## Regla

Si piden torta/pie/circular de categorías → `plot_category_sales_pie`. Si piden barras → `plot_category_sales_bar` o `plot_sales_by_month`. Si piden líneas → `plot_sales_by_month_line`. Si piden scatter/dispersión ventas-reviews → `plot_sales_vs_reviews_scatter`. Si piden scatter/gráfico con columnas no predefinidas → `describe_table` + `plot_query`.

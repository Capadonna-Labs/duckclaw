---
name: olist-reviews
description: Satisfacción y valoraciones de clientes
allowed-tools: get_review_metrics plot_review_score_pie plot_sales_vs_reviews_scatter plot_query describe_table
---

# Reviews / Satisfacción

## Cuándo activar

- "Satisfacción"
- "Reviews"
- "Valoraciones"
- "Puntuación media"
- "Gráfico de valoraciones"
- "Gráfico de dispersión"
- "Scatter"
- "Ventas contra reviews"
- "Correlación ventas reviews"

## Herramientas

- `get_review_metrics`: nota media, buenas/malas reviews.
- `plot_review_score_pie`: diagrama de torta de puntuaciones.
- `plot_sales_vs_reviews_scatter`: gráfico de dispersión (scatter) valor del pedido vs puntuación del review. Usar cuando pidan scatter, dispersión o ventas contra reviews.
- `plot_query`: CUALQUIER gráfico desde SQL. Para combinaciones no predefinidas.
- `describe_table`: columnas de una tabla. Usar antes de plot_query.

## Regla

Para datos → `get_review_metrics`. Para torta de valoraciones → `plot_review_score_pie`. Para scatter/dispersión ventas vs reviews → `plot_sales_vs_reviews_scatter`. Para scatter con columnas custom → `describe_table` + `plot_query`.

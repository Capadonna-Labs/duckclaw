---
name: olist-vendedores
description: Ranking de vendedores por ventas (datos y gráficas)
allowed-tools: get_top_sellers plot_top_sellers_bar
---

# Vendedores

## Cuándo activar

- "¿Cuál es el vendedor con más ventas?"
- "Mejores vendedores"
- "Top sellers"
- "Gráfico de vendedores"

## Herramientas

- `get_top_sellers`: ranking por valor total vendido. Args: limit (default 10).
- `plot_top_sellers_bar`: gráfico de barras. Args: limit (default 10).

## Regla

Para datos numéricos → `get_top_sellers`. Para gráfica → `plot_top_sellers_bar`.

---
name: olist-clientes
description: Clientes top por ventas y candidatos a fidelizar
allowed-tools: get_top_customers_by_sales get_customers_to_retain plot_top_customers_bar
---

# Clientes

## Cuándo activar

- "Clientes que más compran"
- "Top clientes"
- "Clientes a fidelizar"
- "Clientes recurrentes"
- "Gráfico de clientes top"

## Herramientas

- `get_top_customers_by_sales`: ranking por valor comprado. Args: limit (default 15).
- `get_customers_to_retain`: recurrentes (min_orders). Args: limit (default 15), min_orders (default 2).
- `plot_top_customers_bar`: gráfico de barras. Args: limit (default 10).

## Regla

Para ranking por ventas → `get_top_customers_by_sales`. Para fidelización → `get_customers_to_retain`.

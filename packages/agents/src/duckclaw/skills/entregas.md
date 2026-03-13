---
name: olist-entregas
description: Métricas de tiempo de entrega y casos críticos
allowed-tools: get_delivery_metrics get_delivery_critical_cases plot_delivery_days_histogram
---

# Entregas

## Cuándo activar

- "¿Promedio de tiempo de entrega?"
- "Días de entrega"
- "Casos críticos de entrega"
- "Entregas tardías"
- "Histograma de entregas"

## Herramientas

- `get_delivery_metrics`: promedio, mín, máx de días. Sin args.
- `get_delivery_critical_cases`: entregas > X días. Args: days_threshold (default 20), limit (default 30).
- `plot_delivery_days_histogram`: histograma de días. Sin args.

## Regla

Para métricas → `get_delivery_metrics`. Para casos graves → `get_delivery_critical_cases`. Para gráfica → `plot_delivery_days_histogram`. Si piden ambos (promedio + críticos), usa las dos herramientas.

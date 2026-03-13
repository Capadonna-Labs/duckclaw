"""BI helpers for DuckClaw: Olist dataset load, business queries, gráficas y agente con LLM (Groq)."""

from duckclaw.bi.olist import (
    load_olist_data,
    get_top_customers_by_sales,
    get_customers_to_retain,
    get_top_sellers,
    get_delivery_metrics,
    get_delivery_critical_cases,
    get_sales_summary,
    get_review_metrics,
    get_category_sales,
)

__all__ = [
    "load_olist_data",
    "save_grpo_trace",
    "load_grpo_traces",
    "trace_stats",
    "get_top_customers_by_sales",
    "get_customers_to_retain",
    "get_top_sellers",
    "get_delivery_metrics",
    "get_delivery_critical_cases",
    "get_sales_summary",
    "get_review_metrics",
    "get_category_sales",
    "plot_category_sales_bar",
    "plot_category_sales_pie",
    "plot_top_sellers_bar",
    "plot_review_score_pie",
    "plot_delivery_days_histogram",
    "plot_top_customers_bar",
    "plot_sales_by_month_line",
    "plot_sales_vs_reviews_scatter",
    "ask_bi",
    "build_bi_graph",
    "build_olist_bi_tools",
]


def __getattr__(name: str):
    if name in ("ask_bi", "build_bi_graph", "build_olist_bi_tools"):
        from duckclaw.bi import agent
        return getattr(agent, name)
    if name in ("save_grpo_trace", "load_grpo_traces", "trace_stats"):
        from duckclaw.bi import grpo_traces
        return getattr(grpo_traces, name)
    if name in (
        "plot_category_sales_bar",
        "plot_category_sales_pie",
        "plot_top_sellers_bar",
        "plot_review_score_pie",
        "plot_delivery_days_histogram",
        "plot_top_customers_bar",
        "plot_sales_by_month_line",
        "plot_sales_vs_reviews_scatter",
    ):
        from duckclaw.bi import plots
        return getattr(plots, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

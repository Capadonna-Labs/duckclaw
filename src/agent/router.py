"""Agente router: recibe al usuario y enruta a retail (Contador) o agente general."""

from __future__ import annotations

import re
from typing import Any, Optional

# Palabras que indican intención de retail (finanzas, inventario, ventas, gastos)
RETAIR_KEYWORDS = re.compile(
    r"\b(venta|vendí|vendimos|inventario|stock|qué hay|que queda|listar productos|"
    r"gasto|gastos|arriendo|servicios|registra venta|registrar venta|"
    r"precio|pagar|efectivo|tarjeta|transferencia|talla|xl|2xl|blusa|pantalón|camisa)\b",
    re.IGNORECASE,
)


def get_route(incoming: str, has_retail: bool) -> str:
    """Decide si enrutar a retail (Contador) o al agente general.
    has_retail: True si hay store_db disponible."""
    if not has_retail:
        return "general"
    text = (incoming or "").strip()
    if not text:
        return "general"
    if RETAIR_KEYWORDS.search(text):
        return "retail"
    return "general"


def build_router_graph(
    db: Any,
    llm: Any,
    store_db: Optional[Any] = None,
    console: Optional[Any] = None,
) -> Any:
    """Grafo que recibe al usuario (state['incoming']) y enruta a retail o general.
    Si store_db es None, siempre usa el agente general."""
    from langgraph.graph import END, StateGraph

    from duckclaw.integrations.llm_providers import build_agent_graph
    from .graph import build_retail_graph

    has_retail = store_db is not None
    retail_graph = build_retail_graph(store_db or db, llm, console=console) if has_retail else None
    general_graph = build_agent_graph(db, llm)

    def route_node(state: dict) -> dict:
        incoming = (state.get("incoming") or "").strip()
        route = get_route(incoming, has_retail)
        return {"route": route}

    def retail_node(state: dict) -> dict:
        result = retail_graph.invoke({"incoming": state.get("incoming", "")})
        return {"reply": result.get("reply") or "Sin respuesta."}

    def general_node(state: dict) -> dict:
        result = general_graph.invoke({"incoming": state.get("incoming", "")})
        return {"reply": result.get("reply") or "Sin respuesta."}

    graph = StateGraph(dict)
    graph.add_node("route", route_node)
    if has_retail:
        graph.add_node("retail", retail_node)
    graph.add_node("general", general_node)
    graph.set_entry_point("route")

    def after_route(state: dict) -> str:
        return state.get("route") or "general"

    if has_retail:
        graph.add_conditional_edges("route", after_route, {"retail": "retail", "general": "general"})
        graph.add_edge("retail", END)
    else:
        graph.add_edge("route", "general")
    graph.add_edge("general", END)

    return graph.compile()

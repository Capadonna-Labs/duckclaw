"""
Entry router agent (LangGraph): single entrypoint for user messages.

State contract:
  - Input:  incoming (str), history (optional list of {role, content})
  - Internal: route ("retail" | "general")
  - Output:  reply (str, always present)

API: build_entry_router_graph(db, llm, *, store_db=None, console=None, system_prompt="",
  llm_provider="", llm_model="")
  returns a compiled LangGraph. Invoke with: graph.invoke({"incoming": text, "history": history or []}).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

# Tablas mínimas para considerar la DB como Olist (BI agent)
_OLIST_REQUIRED = {"olist_orders", "olist_order_items", "olist_sellers"}

# Mapeo intención → (tool, args). El router decide la herramienta antes de invocar LLM.
_OLIST_INTENT_MAP: list[tuple[re.Pattern, str, dict]] = [
    (re.compile(r"\b(cu[aá]ntas?\s+tablas?|cu[aá]ntas?\s+tablas?\s+hay|qu[eé]\s+tablas?|tablas?\s+disponibles?|tablas?\s+hay|esquema|estructura)\b", re.I), "list_tables", {}),
    (re.compile(r"\b(vendedor\s+con\s+m[aá]s\s+ventas?|mejores?\s+vendedores?|top\s+sellers?)\b", re.I), "get_top_sellers", {"limit": 10}),
    (re.compile(r"\b(promedio\s+de\s+entrega|tiempo\s+de\s+entrega|d[ií]as\s+de\s+entrega)\b", re.I), "get_delivery_metrics", {}),
    (re.compile(r"\b(casos?\s+cr[ií]ticos?|entregas?\s+tard[ií]as?)\b", re.I), "get_delivery_critical_cases", {"days_threshold": 20, "limit": 30}),
    (re.compile(r"\b(resumen\s+de\s+ventas?|total\s+pedidos?|ticket\s+medio)\b", re.I), "get_sales_summary", {}),
    (re.compile(r"\b(categor[ií]as?\s+m[aá]s\s+vendidas?|ventas?\s+por\s+categor[ií]a)\b", re.I), "get_category_sales", {"limit": 15}),
    (re.compile(r"\b(clientes?\s+que\s+m[aá]s\s+compran?|top\s+clientes?)\b", re.I), "get_top_customers_by_sales", {"limit": 15}),
    (re.compile(r"\b(ventas?\s+por\s+mes|evoluci[oó]n\s+mensual)\b", re.I), "get_sales_by_month", {}),
    (re.compile(r"\b(satisfacci[oó]n|reviews?|valoraciones?)\b", re.I), "get_review_metrics", {}),
]


def _has_olist_schema(db: Any) -> bool:
    """True si la DB tiene el esquema Olist (permite usar ask_bi)."""
    try:
        r = db.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' ORDER BY table_name"
        )
        rows = json.loads(r) if isinstance(r, str) else (r or [])
        names = {row.get("table_name") for row in rows if isinstance(row, dict)}
        return _OLIST_REQUIRED.issubset(names)
    except Exception:
        return False


def _normalize_incoming(text: str) -> str:
    """Normaliza el texto para clasificación (strip, unicode, espacios)."""
    if not text:
        return ""
    t = text.strip()
    # Normalizar caracteres unicode comunes (ej. ñ vs n)
    t = t.replace("\u00a0", " ")  # non-breaking space
    t = " ".join(t.split())
    return t.lower()


# Herramientas que devuelven solo datos (no gráficas). Si el usuario pide "gráfico/scatter", usar ask_bi.
_DATA_ONLY_TOOLS = frozenset({
    "get_category_sales", "get_sales_by_month", "get_top_customers_by_sales", "get_review_metrics",
})

_CHART_KEYWORDS = re.compile(
    r"\b(gr[aá]fico|diagrama|gr[aá]fica|chart|torta|barras?|circular|pie|l[ií]neas?|scatter|dispersi[oó]n|heatmap|mapa\s+de\s+calor)\b",
    re.I,
)

_EXPORT_FILE_KEYWORDS = re.compile(
    r"\b(excel|xlsx|markdown|\.md|md\b|reporte\s+md|exportar|exporta|exporte|descargar|descarga|archivo\s+(?:excel|markdown|md|para\s+descargar)|hoja\s+de\s+c[aá]lculo)\b",
    re.I,
)


def _classify_olist_intent(incoming: str) -> Optional[tuple[str, dict]]:
    """
    Clasifica la intención y devuelve (tool_name, args) o None.
    Si varias intenciones coinciden (p. ej. "promedio de entrega y casos críticos"),
    devuelve None para que ask_bi maneje la consulta compuesta.
    Si el usuario pide "gráfico/diagrama" y la herramienta es solo datos, devuelve None para ask_bi.
    """
    text = _normalize_incoming(incoming)
    if not text:
        return None
    matches: list[tuple[str, dict]] = []
    for pattern, tool, args in _OLIST_INTENT_MAP:
        if pattern.search(text):
            matches.append((tool, dict(args)))
    if len(matches) == 1:
        tool_name, args = matches[0]
        # Si piden gráfico/diagrama y la herramienta es solo datos → ask_bi (tiene plot_*)
        if tool_name in _DATA_ONLY_TOOLS and _CHART_KEYWORDS.search(incoming):
            return None
        # Si piden Excel/Markdown/exportar → ask_bi (tiene export_to_excel, export_to_markdown)
        if _EXPORT_FILE_KEYWORDS.search(incoming):
            return None
        return (tool_name, args)
    # Varias intenciones → ask_bi para respuesta compuesta
    return None


def _execute_olist_tool_direct(db: Any, tool_name: str, args: dict) -> str:
    """Ejecuta la herramienta Olist directamente y formatea la respuesta."""
    from duckclaw.bi import olist as bi_olist

    def _fmt(v: Any) -> str:
        if v is None:
            return "?"
        s = str(v)
        try:
            f = float(s.replace(",", "."))
            return f"{f:,.1f}" if f != int(f) else f"{int(f):,}"
        except (ValueError, TypeError):
            return s

    try:
        fn = getattr(bi_olist, tool_name, None)
        if not callable(fn):
            return f"Herramienta desconocida: {tool_name}"
        data = fn(db, **args) if args else fn(db)
        if not isinstance(data, list):
            return str(data)[:500]
        if not data:
            return "No hay datos."
        if tool_name == "list_tables":
            tables = [t.get("table_name", "?") for t in data if isinstance(t, dict)]
            return f"Hay {len(tables)} tablas: {', '.join(tables)}."
        if tool_name == "get_top_sellers":
            items = data[:5]
            parts = [f"{i.get('seller_city', i.get('seller_id', '?'))} ({_fmt(i.get('total_sales'))})" for i in items]
            return f"Los mejores vendedores: {', '.join(parts)}. Total: {len(data)} vendedores."
        if tool_name == "get_delivery_metrics":
            d = data[0] if data else {}
            avg = d.get("avg_delivery_days", d.get("avg_days", "?"))
            mn = d.get("min_delivery_days", d.get("min_days", "?"))
            mx = d.get("max_delivery_days", d.get("max_days", "?"))
            return f"Tiempo de entrega: promedio {_fmt(avg)} días (mín: {_fmt(mn)}, máx: {_fmt(mx)})."
        if tool_name == "get_delivery_critical_cases":
            top = data[:5]
            parts = [f"{_fmt(r.get('delivery_days'))} días (pedido {r.get('order_id', '?')[:12]}...)" for r in top]
            return f"Hay {len(data)} casos críticos. Los más graves: {'; '.join(parts)}."
        if tool_name == "get_sales_summary":
            d = data[0] if data else {}
            return f"Resumen: {_fmt(d.get('total_orders'))} pedidos, ventas totales {_fmt(d.get('total_sales'))}, ticket promedio {_fmt(d.get('avg_ticket'))}."
        if tool_name == "get_category_sales":
            items = data[:5]
            parts = [f"{i.get('category', '?')} ({_fmt(i.get('total_sales'))})" for i in items]
            return f"Ventas por categoría: {', '.join(parts)}. Total: {len(data)} categorías."
        if tool_name == "get_top_customers_by_sales":
            items = data[:5]
            parts = [f"{i.get('customer_city', '?')} ({_fmt(i.get('total_sales'))})" for i in items]
            return f"Clientes top: {', '.join(parts)}. Total: {len(data)} clientes."
        if tool_name == "get_review_metrics":
            d = data[0] if data else {}
            return f"Satisfacción: nota media {_fmt(d.get('avg_score'))}, reviews buenas {_fmt(d.get('good_reviews'))}, malas {_fmt(d.get('bad_reviews'))}."
        if tool_name == "get_sales_by_month":
            items = data[:5]
            parts = [f"{i.get('month', '?')} ({_fmt(i.get('total_sales'))})" for i in items]
            return f"Ventas por mes: {', '.join(parts)}. Total: {len(data)} meses."
        return f"{len(data)} registros obtenidos."
    except Exception as e:
        return f"Error: {e}"


def _load_skills_context() -> str:
    """Carga todos los .md de duckclaw/skills/ como contexto para el modelo."""
    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    if not skills_dir.is_dir():
        return ""
    parts: list[str] = []
    for f in sorted(skills_dir.glob("*.md")):
        if f.name.upper() == "README.MD":
            continue
        parts.append(f.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts) if parts else ""


# Keywords that indicate retail intent (finanzas, inventario, ventas, gastos)
RETAIL_KEYWORDS = re.compile(
    r"\b(venta|vendí|vendimos|inventario|stock|qué hay|que queda|listar productos|"
    r"gasto|gastos|gastar|arriendo|servicios|registra venta|registrar venta|"
    r"precio|pagar|efectivo|tarjeta|transferencia|talla|xl|2xl|blusa|pantalón|camisa)\b",
    re.IGNORECASE,
)


def _route_by_keywords(incoming: str, has_retail: bool) -> Optional[str]:
    """Rule-based route. Returns 'retail' or 'general', or None if ambiguous."""
    if not has_retail:
        return "general"
    text = (incoming or "").strip()
    if not text:
        return "general"
    if RETAIL_KEYWORDS.search(text):
        return "retail"
    return "general"


def get_route(incoming: str, has_retail: bool) -> str:
    """Decide route: 'retail' or 'general'. has_retail: True if store_db is available."""
    return _route_by_keywords(incoming, has_retail) or "general"


def build_entry_router_graph(
    db: Any,
    llm: Any,
    *,
    store_db: Optional[Any] = None,
    console: Optional[Any] = None,
    system_prompt: str = "",
    llm_provider: str = "",
    llm_model: str = "",
    save_traces: bool = False,
    send_to_langsmith: bool = False,
) -> Any:
    """
    Build the entry LangGraph: route (hybrid) -> retail or general -> reply.

    State: incoming (str), history (optional list), route (internal), reply (output).
    Si la DB tiene esquema Olist, el path general usa ask_bi (misma calidad que notebook).
    """
    from langgraph.graph import END, StateGraph

    from duckclaw.agents.general_graph import build_general_graph
    from duckclaw.agents.retail_graph import build_retail_graph

    has_retail = store_db is not None
    has_olist = _has_olist_schema(db)
    provider = (llm_provider or "").strip().lower()
    model = (llm_model or "").strip()

    retail_graph = (
        build_retail_graph(store_db or db, llm, console=console, system_prompt=system_prompt) if has_retail else None
    )
    general_graph = build_general_graph(db, llm, system_prompt=system_prompt)

    def route_node(state: dict) -> dict:
        incoming = (state.get("incoming") or "").strip()
        history = state.get("history") or []
        # 1) Rules first
        route = _route_by_keywords(incoming, has_retail)
        # 2) LLM fallback only when ambiguous (no keyword match and short/neutral message)
        if route == "general" and has_retail and _is_ambiguous(incoming):
            route = _route_by_llm(llm, incoming, history)
        out = {"route": route or "general", "incoming": incoming, "history": history}
        if "graph_context" in state:
            out["graph_context"] = state.get("graph_context") or ""
        return out

    def retail_node(state: dict) -> dict:
        assert retail_graph is not None
        result = retail_graph.invoke({
            "incoming": state.get("incoming", ""),
        })
        return {"reply": result.get("reply") or "Sin respuesta."}

    def _store_name_from_prompt(prompt: str) -> str:
        """Extrae el nombre de la tienda del system_prompt (ej. 'asistente de Lumi Store')."""
        if not prompt:
            return "Lumi Store"
        m = re.search(r"asistente\s+de\s+([^,.\n]+?)(?:\s*,\s*una\s+tienda|\s*\.|$)", prompt, re.I)
        return (m.group(1).strip() or "Lumi Store") if m else "Lumi Store"

    def general_node(state: dict) -> dict:
        incoming = (state.get("incoming") or "").strip()
        # Preguntas sobre nombre de la tienda → respuesta directa
        if re.search(r"\b(nombre\s+de\s+la\s+tienda|c[oó]mo\s+se\s+llama\s+la\s+tienda|qu[eé]\s+tienda\s+es|nombre\s+tienda)\b", incoming, re.I):
            store = _store_name_from_prompt(system_prompt)
            return {"reply": f"La tienda se llama {store}."}
        if has_olist:
            try:
                # 1) Router decide: intent único → direct tool call (sin LLM)
                intent = _classify_olist_intent(incoming)
                if intent:
                    tool_name, args = intent
                    reply = _execute_olist_tool_direct(db, tool_name, args)
                    return {"reply": reply or "Sin respuesta."}
                # 2) Consulta compuesta o ambigua → ask_bi con SKILLS (requiere provider)
                if provider:
                    from duckclaw.bi import ask_bi
                    skills_ctx = _load_skills_context()
                    store_ctx = (
                        f"Contexto: La tienda se llama {_store_name_from_prompt(system_prompt)}. "
                        "Usa el historial de conversación para responder preguntas cortas de seguimiento."
                    )
                    report_hint = ""
                    if re.search(r"\b(reporte|informe|insights)\s+.*\b(md|markdown)\b", incoming, re.I) or re.search(r"\b(md|markdown)\s+.*\b(reporte|informe|insights)\b", incoming, re.I):
                        report_hint = (
                            "\n\nIMPORTANTE REPORTE MD: Usar SOLO create_report_markdown. UN archivo con nombre descriptivo (ventas_noviembre_2017). "
                            "Los insights van DENTRO del MD, no en el mensaje. NUNCA export_to_excel para reportes."
                        )
                    prompt_extra = f"{store_ctx}\n\n{skills_ctx}{report_hint}" if (skills_ctx or report_hint) else store_ctx
                    reply = ask_bi(
                        db,
                        incoming,
                        provider=provider or "deepseek",
                        model=model or "",
                        system_prompt_extra=prompt_extra,
                        history=state.get("history") or [],
                        save_traces=save_traces,
                        send_to_langsmith=send_to_langsmith,
                    )
                    return {"reply": reply or "Sin respuesta."}
            except Exception as e:
                return {"reply": f"Error BI: {e}"}
        result = general_graph.invoke({
            "incoming": incoming,
            "history": state.get("history") or [],
            "graph_context": state.get("graph_context") or "",
        })
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


def _is_ambiguous(text: str) -> bool:
    """Consider short or generic messages as ambiguous for routing."""
    t = (text or "").strip()
    if len(t) < 3:
        return False
    # Very short or greeting-like -> ambiguous
    if len(t) < 15 and re.match(r"^(hola|hey|buenas|qué tal|ayuda|help|que puedes)\b", t, re.I):
        return True
    return False


def _route_by_llm(llm: Any, incoming: str, history: list) -> str:
    """Use LLM to classify intent: retail vs general. Returns 'retail' or 'general'."""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        system = (
            "Clasifica la intención del usuario en una sola palabra: 'retail' o 'general'. "
            "'retail' = ventas, inventario, gastos, productos, precios, tallas, pagos. "
            "'general' = consultas SQL, datos, tablas, otra cosa. Responde solo la palabra."
        )
        user = f"Mensaje: {incoming}"
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        content = (getattr(resp, "content", None) or str(resp)).strip().lower()
        if "retail" in content:
            return "retail"
    except Exception:
        pass
    return "general"

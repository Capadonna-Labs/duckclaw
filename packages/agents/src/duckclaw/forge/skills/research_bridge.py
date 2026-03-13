"""
Research Bridge — Tavily search + Browser-Use navigation.

Spec: specs/Pipeline_de_Investigación_y_Navegacion_Autonoma_(Tavily+Browser-Use).md
Requiere: pip install tavily-python  (o uv sync --extra tavily)
          pip install browser-use playwright  (o uv sync --extra browser)
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

_TAVILY_ENV = "TAVILY_API_KEY"


def _run_async_from_sync(coro) -> Any:
    """
    Ejecuta una coroutine desde contexto síncrono.
    Si ya hay un event loop corriendo (ej. Telegram, FastAPI), usa un thread
    separado para evitar 'RuntimeError: This event loop is already running'.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


def _tavily_available() -> bool:
    """True si tavily-python está instalado y hay API key."""
    try:
        import tavily  # noqa: F401
        return bool(os.environ.get(_TAVILY_ENV, "").strip())
    except ImportError:
        return False


def _browser_use_available() -> bool:
    """True si browser-use está instalado."""
    try:
        import browser_use  # noqa: F401
        return True
    except ImportError:
        return False


def _format_tavily_results(response: Any) -> str:
    """Convierte la respuesta de Tavily a Markdown legible."""
    parts: list[str] = []
    answer = getattr(response, "answer", None) or (response.get("answer") if isinstance(response, dict) else None)
    if answer:
        parts.append(f"## Respuesta\n{answer}\n")
    results = getattr(response, "results", None) or (response.get("results", []) if isinstance(response, dict) else [])
    if results:
        parts.append("## Fuentes\n")
        for i, r in enumerate(results, 1):
            title = getattr(r, "title", None) or (r.get("title") if isinstance(r, dict) else "Sin título")
            url = getattr(r, "url", None) or (r.get("url") if isinstance(r, dict) else "")
            content = getattr(r, "content", None) or (r.get("content") if isinstance(r, dict) else "")
            parts.append(f"{i}. **{title}**\n   - URL: {url}\n")
            if content:
                parts.append(f"   - {content[:500]}{'...' if len(str(content)) > 500 else ''}\n")
    return "\n".join(parts) if parts else "No se encontraron resultados."


def _tavily_search_tool(config: Optional[dict] = None) -> Optional[Any]:
    """
    Crea un StructuredTool para búsqueda Tavily.
    config: tavily_enabled, search_depth, include_answer, max_results, topic.
    """
    if not _tavily_available():
        return None
    cfg = config or {}
    if cfg.get("tavily_enabled") is False:
        return None

    from langchain_core.tools import StructuredTool
    from tavily import TavilyClient

    api_key = os.environ.get(_TAVILY_ENV, "").strip()
    if not api_key:
        return None

    search_depth = cfg.get("search_depth", "advanced")
    include_answer = cfg.get("include_answer", True)
    max_results = cfg.get("max_results", 10)
    topic = cfg.get("topic", "general")

    def _search(query: str) -> str:
        try:
            client = TavilyClient(api_key=api_key)
            response = client.search(
                query=query,
                search_depth=search_depth,
                include_answer=include_answer,
                max_results=max_results,
                topic=topic,
            )
            return _format_tavily_results(response)
        except Exception as e:
            return f"Error Tavily: {e}"

    return StructuredTool.from_function(
        _search,
        name="tavily_search",
        description="Busca en internet con Tavily. Usa para preguntas que requieren información actualizada o no están en la base de datos local. Parámetros: query (consulta de búsqueda).",
    )


def _browser_navigate_tool(
    config: Optional[dict] = None,
    llm: Optional[Any] = None,
) -> Optional[Any]:
    """
    Crea un StructuredTool para navegación con browser-use.
    config: browser_enabled, allowed_domains.
    Phase 2: ejecución dentro del Strix Sandbox (requiere Playwright en imagen Docker).
    """
    if not _browser_use_available() or llm is None:
        return None
    cfg = config or {}
    if cfg.get("browser_enabled") is False:
        return None

    from langchain_core.tools import StructuredTool

    allowed_domains = cfg.get("allowed_domains") or []

    def _browse(url: str, task: str) -> str:
        # TODO Phase 2: ejecutar dentro del Strix Sandbox con dominio whitelisting
        if allowed_domains:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            if domain and not any(d in domain for d in allowed_domains):
                return f"[Seguridad] El dominio {domain} no está en la lista permitida: {allowed_domains}"
        try:
            from browser_use import Agent as BrowserAgent
            try:
                from browser_use import Browser
            except ImportError:
                from browser_use.browser.browser import Browser

            # Perfil limpio: sin cookies, historial ni caché persistente (Habeas Data)
            browser = Browser()
            agent = BrowserAgent(
                task=f"Navega a {url} y {task}",
                llm=llm,
                browser=browser,
            )
            result = _run_async_from_sync(agent.run())
            return str(result) if result is not None else "Navegación completada."
        except Exception as e:
            return f"Error browser-use: {e}"

    return StructuredTool.from_function(
        _browse,
        name="browser_navigate",
        description="Navega a una URL y ejecuta una tarea (extraer datos, rellenar formularios, etc.). Usa cuando una búsqueda simple no basta. Parámetros: url (p. ej. https://ejemplo.com), task (qué hacer en la página).",
    )


def register_research_skill(
    tools_list: list[Any],
    research_config: Optional[dict] = None,
    *,
    llm: Optional[Any] = None,
) -> None:
    """
    Registra las herramientas de investigación (Tavily, browser-use) en la lista.
    Llamar desde build_worker_graph cuando el manifest tiene skills.research.
    """
    if not research_config:
        return
    try:
        tavily_tool = _tavily_search_tool(research_config)
        if tavily_tool:
            tools_list.append(tavily_tool)
        browser_tool = _browser_navigate_tool(research_config, llm=llm)
        if browser_tool:
            tools_list.append(browser_tool)
    except Exception:
        pass

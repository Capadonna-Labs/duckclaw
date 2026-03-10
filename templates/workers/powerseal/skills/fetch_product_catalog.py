"""Skill: fetch_product_catalog — obtiene productos desde la web de Power Seal."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.tools import StructuredTool

# URL del catálogo (configurable vía env)
POWERSEAL_CATALOG_URL = os.environ.get("POWERSEAL_CATALOG_URL", "https://www.powerseal.com/")

def get_tools(db: Any, schema_name: str, spec: Any = None) -> list:
    def fetch_product_catalog(url: str = "") -> str:
        """
        Obtiene el catálogo de productos desde la URL. Si url está vacío, usa POWERSEAL_CATALOG_URL.
        Retorna texto estructurado con productos para el LLM.
        """
        target_url = (url or "").strip() or POWERSEAL_CATALOG_URL
        try:
            import urllib.request
            req = urllib.request.Request(
                target_url,
                headers={"User-Agent": "DuckClaw-PowerSeal/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            return json.dumps({"error": f"No se pudo obtener el catálogo: {e}"})

        # Intentar BeautifulSoup si está disponible
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            soup.find_all("script")
            text = soup.get_text(separator="\n", strip=True)
        except ImportError:
            # Fallback: regex para eliminar tags
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()

        # Limitar tamaño para el LLM
        if len(text) > 8000:
            text = text[:8000] + "\n[... truncado ...]"
        return json.dumps({"url": target_url, "content": text[:8000]})

    return [
        StructuredTool.from_function(
            fetch_product_catalog,
            name="fetch_product_catalog",
            description="Obtiene el catálogo de productos desde la web de Power Seal. url: opcional, default POWERSEAL_CATALOG_URL. Retorna contenido para consultas.",
        )
    ]

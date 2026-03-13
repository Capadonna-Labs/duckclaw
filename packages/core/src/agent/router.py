"""Deprecated: use duckclaw.agents.router instead.

This module is a compatibility shim. Prefer:
  from duckclaw.agents.router import build_entry_router_graph, get_route
"""

from __future__ import annotations

import warnings
from typing import Any, Optional

from duckclaw.agents.router import get_route  # noqa: F401


def build_router_graph(
    db: Any,
    llm: Any,
    store_db: Optional[Any] = None,
    console: Optional[Any] = None,
) -> Any:
    """Deprecated. Use duckclaw.agents.router.build_entry_router_graph."""
    warnings.warn(
        "src.agent.router.build_router_graph is deprecated; use duckclaw.agents.router.build_entry_router_graph.",
        DeprecationWarning,
        stacklevel=2,
    )
    from duckclaw.agents.router import build_entry_router_graph

    return build_entry_router_graph(
        db,
        llm,
        store_db=store_db,
        console=console,
        system_prompt="",
    )


__all__ = ["build_router_graph", "get_route"]

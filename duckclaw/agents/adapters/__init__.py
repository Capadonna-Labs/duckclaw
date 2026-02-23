"""Adapters: integración agnóstica con LangGraph, OpenAI, CrewAI."""

from .base import BaseAgent

def __getattr__(name: str):
    if name == "LangGraphAdapter":
        from .langgraph_adapter import LangGraphAdapter
        return LangGraphAdapter
    if name == "OpenAIAdapter":
        from .openai_adapter import OpenAIAdapter
        return OpenAIAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["BaseAgent", "LangGraphAdapter", "OpenAIAdapter"]

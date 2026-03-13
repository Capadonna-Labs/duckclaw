"""DuckDB Native RAG — Vector Similarity Search para catálogos.

Spec: specs/DuckDB_Native_RAG_Vector_Search.md
"""

from duckclaw.forge.rag.embeddings import embed_text, get_embedding_model
from duckclaw.forge.rag.catalog import ensure_catalog_schema, search_catalog_semantic

__all__ = [
    "embed_text",
    "get_embedding_model",
    "ensure_catalog_schema",
    "search_catalog_semantic",
]

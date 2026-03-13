"""Embeddings locales: sentence-transformers o fallback."""

from __future__ import annotations

from typing import Any, List, Optional

_EMBEDDING_MODEL: Any = None
_EMBEDDING_DIM = 384  # all-MiniLM-L6-v2; nomic-embed-text usa 768


def get_embedding_model():
    """Carga el modelo de embeddings (lazy). Retorna None si no está disponible."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL
    try:
        from sentence_transformers import SentenceTransformer
        # all-MiniLM-L6-v2: 384 dim, rápido, sin GPU
        _EMBEDDING_MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        return _EMBEDDING_MODEL
    except ImportError:
        return None


def embed_text(text: str) -> Optional[List[float]]:
    """Vectoriza texto. Retorna None si el modelo no está disponible."""
    model = get_embedding_model()
    if model is None:
        return None
    emb = model.encode(text, convert_to_numpy=True)
    return emb.tolist()

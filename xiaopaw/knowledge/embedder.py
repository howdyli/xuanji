"""Batch embedding for knowledge-base chunks.

Reuses the OpenAI-compatible client from ``xiaopaw.memory.indexer`` and the
``qwen3.7-text-embedding`` model (1024 dims). The dimension matches the
``knowledge_chunks`` pgvector column; the memory subsystem may use a different
model independently, since each subsystem only needs internal consistency
between the vectors it stores and the queries it embeds.
"""

from __future__ import annotations

import logging
from functools import cache

logger = logging.getLogger(__name__)

EMBED_MODEL = "qwen3.7-text-embedding"
EMBED_DIM = 1024
_BATCH_SIZE = 16
_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class EmbeddingError(RuntimeError):
    """Raised when embeddings cannot be produced."""


@cache
def _get_embed_client():
    """OpenAI-compatible client for knowledge embeddings.

    When ``KNOWLEDGE_EMBED_API_KEY`` is set, build a dedicated client so the
    knowledge base can target its own provider (e.g. DashScope for the
    ``qwen3.7-text-embedding`` model) via ``KNOWLEDGE_EMBED_BASE_URL`` without
    disturbing the shared memory/chat client. Otherwise fall back to the shared
    client from ``xiaopaw.memory.indexer``.
    """
    import os

    api_key = os.environ.get("KNOWLEDGE_EMBED_API_KEY")
    if api_key:
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai package not installed, knowledge embedding disabled")
            return None
        base_url = os.environ.get("KNOWLEDGE_EMBED_BASE_URL", _DEFAULT_BASE_URL)
        return OpenAI(api_key=api_key, base_url=base_url)

    from xiaopaw.memory.indexer import _get_llm_client

    return _get_llm_client()


def embed_texts(texts: list[str], *, batch_size: int = _BATCH_SIZE) -> list[list[float]]:
    """Embed ``texts`` in batches, preserving input order.

    Raises ``EmbeddingError`` if the embedding client is unavailable so the
    caller can mark the document ``failed`` rather than storing null vectors.
    """
    if not texts:
        return []

    client = _get_embed_client()
    if client is None:
        raise EmbeddingError("embedding client unavailable (openai package / API key missing)")

    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        resp = client.embeddings.create(model=EMBED_MODEL, input=batch, dimensions=EMBED_DIM)
        # OpenAI SDK returns data in request order, but sort defensively by index.
        ordered = sorted(resp.data, key=lambda d: d.index)
        vectors.extend([d.embedding for d in ordered])

    if len(vectors) != len(texts):
        raise EmbeddingError(
            f"embedding count mismatch: got {len(vectors)} for {len(texts)} inputs"
        )
    return vectors


def embed_query(text: str) -> list[float]:
    """Embed a single query string."""
    return embed_texts([text])[0]

"""Batch embedding for knowledge-base chunks.

Reuses the OpenAI-compatible client from ``xiaopaw.memory.indexer`` and the
``qwen3.7-text-embedding`` model (1024 dims). The dimension matches the
``knowledge_chunks`` pgvector column; the memory subsystem may use a different
model independently, since each subsystem only needs internal consistency
between the vectors it stores and the queries it embeds.
"""

from __future__ import annotations

import hashlib
import logging
from functools import cache

logger = logging.getLogger(__name__)

EMBED_MODEL = "qwen3.7-text-embedding"
EMBED_DIM = 1024
_BATCH_SIZE = 16
_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Embedding cache: SHA256(text)[:16] -> vector
_embed_cache: dict[str, list[float]] = {}
_EMBED_CACHE_MAX = 10000


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


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

    # Check cache
    results: list[list[float] | None] = [None] * len(texts)
    uncached_indices: list[int] = []
    uncached_texts: list[str] = []

    for i, text in enumerate(texts):
        key = _cache_key(text)
        cached = _embed_cache.get(key)
        if cached is not None:
            results[i] = cached
        else:
            uncached_indices.append(i)
            uncached_texts.append(text)

    # Fetch uncached texts via API
    if uncached_texts:
        client = _get_embed_client()
        if client is None:
            raise EmbeddingError("embedding client unavailable (openai package / API key missing)")

        new_vectors: list[list[float]] = []
        for start in range(0, len(uncached_texts), batch_size):
            batch = uncached_texts[start : start + batch_size]
            resp = client.embeddings.create(model=EMBED_MODEL, input=batch, dimensions=EMBED_DIM)
            # OpenAI SDK returns data in request order, but sort defensively by index.
            ordered = sorted(resp.data, key=lambda d: d.index)
            new_vectors.extend([d.embedding for d in ordered])

        # Fill results and update cache
        for idx, vec in zip(uncached_indices, new_vectors):
            results[idx] = vec
            if len(_embed_cache) < _EMBED_CACHE_MAX:
                _embed_cache[_cache_key(texts[idx])] = vec

    return [r for r in results]  # type: ignore[misc]


_query_cache: dict[str, list[float]] = {}
_QUERY_CACHE_MAX = 500


def embed_query(text: str) -> list[float]:
    """Embed a single query string with LRU cache."""
    key = _cache_key(text)
    cached = _query_cache.get(key)
    if cached is not None:
        return cached
    result = embed_texts([text])[0]
    if len(_query_cache) >= _QUERY_CACHE_MAX:
        # Evict half the cache
        keys = list(_query_cache.keys())
        for k in keys[: len(keys) // 2]:
            del _query_cache[k]
    _query_cache[key] = result
    return result

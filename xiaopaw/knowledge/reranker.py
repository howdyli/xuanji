"""Reranking layer for knowledge-base retrieval.

Supports three backends:
- LocalReranker: bge-reranker-v2-m3 via FlagEmbedding (default, zero marginal cost)
- APIReranker: DashScope gte-rerank-hybrid (optional, network-dependent)
- NoopReranker: pass-through for degradation / A/B comparison
"""

from __future__ import annotations

import logging
import os
import time
from typing import Protocol

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    def rerank(self, query: str, documents: list[str], top_n: int) -> list[dict]:
        """Return list of {index, score} sorted by relevance desc."""
        ...


class LocalReranker:
    """bge-reranker-v2-m3, lazy-loaded, CPU inference."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self._model_name = model_name
        self._model = None  # lazy load

    def _ensure_model(self):
        if self._model is None:
            from FlagEmbedding import FlagReranker
            self._model = FlagReranker(self._model_name, use_fp16=True)

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[dict]:
        self._ensure_model()
        start = time.monotonic()
        try:
            pairs = [[query, doc] for doc in documents]
            scores = self._model.compute_score(pairs, normalize=True)
            if isinstance(scores, float):
                scores = [scores]
            ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_n]
            elapsed = time.monotonic() - start
            logger.info("local rerank: %d docs in %.3fs", len(documents), elapsed)
            return [{"index": idx, "score": float(sc)} for idx, sc in ranked]
        except Exception as exc:
            logger.warning("local rerank failed, falling back: %s", exc)
            return NoopReranker().rerank(query, documents, top_n)


class APIReranker:
    """DashScope gte-rerank-hybrid via HTTP API."""

    def __init__(self, model: str = "gte-rerank-hybrid"):
        self._model = model
        self._api_key = (
            os.environ.get("KNOWLEDGE_RERANK_API_KEY")
            or os.environ.get("KNOWLEDGE_EMBED_API_KEY")
            or os.environ.get("DASHSCOPE_API_KEY", "")
        )
        self._url = "https://dashscope.aliyuncs.com/api/v1/services/rerank"

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[dict]:
        if not self._api_key:
            logger.warning("API reranker: no API key, falling back")
            return NoopReranker().rerank(query, documents, top_n)
        import httpx
        start = time.monotonic()
        try:
            # Truncate documents to 1000 chars to avoid oversized payload
            truncated = [doc[:1000] for doc in documents]
            payload = {
                "model": self._model,
                "input": {"query": query, "documents": truncated},
            }
            resp = httpx.post(
                self._url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("output", {}).get("results", [])
            elapsed = time.monotonic() - start
            logger.info("API rerank: %d docs in %.3fs", len(documents), elapsed)
            return [
                {"index": r["index"], "score": float(r["relevance_score"])}
                for r in results[:top_n]
            ]
        except Exception as exc:
            logger.warning("API rerank failed, falling back: %s", exc)
            return NoopReranker().rerank(query, documents, top_n)


class NoopReranker:
    """Pass-through: returns documents in original order."""

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[dict]:
        return [{"index": i, "score": 1.0 - i * 0.001} for i in range(min(top_n, len(documents)))]


def get_reranker(backend: str = "local", model: str = "BAAI/bge-reranker-v2-m3") -> Reranker:
    """Factory: create reranker by backend name. Falls back to NoopReranker on error."""
    if backend == "none":
        return NoopReranker()
    if backend == "api":
        return APIReranker()
    if backend == "local":
        try:
            return LocalReranker(model_name=model)
        except Exception as exc:
            logger.warning("local reranker init failed, falling back to noop: %s", exc)
            return NoopReranker()
    logger.warning("unknown reranker backend %r, using noop", backend)
    return NoopReranker()

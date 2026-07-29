"""Tests for xiaopaw.knowledge.reranker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from xiaopaw.knowledge.reranker import (
    APIReranker,
    LocalReranker,
    NoopReranker,
    get_reranker,
)


class TestNoopReranker:
    def test_noop_reranker_returns_original_order(self):
        """NoopReranker should return documents in their original order."""
        reranker = NoopReranker()
        docs = ["doc_a", "doc_b", "doc_c", "doc_d"]
        result = reranker.rerank("query", docs, top_n=3)
        assert len(result) == 3
        assert result[0]["index"] == 0
        assert result[1]["index"] == 1
        assert result[2]["index"] == 2
        # Scores should be descending
        assert result[0]["score"] > result[1]["score"] > result[2]["score"]

    def test_noop_reranker_top_n_exceeds_docs(self):
        reranker = NoopReranker()
        docs = ["only_one"]
        result = reranker.rerank("q", docs, top_n=5)
        assert len(result) == 1
        assert result[0]["index"] == 0


class TestAPIReranker:
    @patch("httpx.post")
    def test_api_reranker_mock(self, mock_post):
        """APIReranker should correctly parse the API response."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "output": {
                "results": [
                    {"index": 2, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.80},
                    {"index": 1, "relevance_score": 0.60},
                ]
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        reranker = APIReranker()
        reranker._api_key = "test-key"  # bypass env var lookup
        docs = ["doc_a", "doc_b", "doc_c"]
        result = reranker.rerank("query", docs, top_n=2)

        assert len(result) == 2
        assert result[0]["index"] == 2
        assert result[0]["score"] == 0.95
        assert result[1]["index"] == 0
        assert result[1]["score"] == 0.80

    def test_api_reranker_no_key_falls_back(self):
        """APIReranker with no API key should fall back to NoopReranker."""
        reranker = APIReranker()
        reranker._api_key = ""
        docs = ["a", "b", "c"]
        result = reranker.rerank("q", docs, top_n=2)
        # Should get noop-style results (original order)
        assert result[0]["index"] == 0
        assert result[1]["index"] == 1


class TestLocalReranker:
    @patch("xiaopaw.knowledge.reranker.FlagReranker", create=True)
    def test_local_reranker_fallback(self, mock_flag_cls):
        """LocalReranker should fall back to NoopReranker on model failure."""
        mock_model = MagicMock()
        mock_model.compute_score.side_effect = RuntimeError("model error")
        mock_flag_cls.return_value = mock_model

        reranker = LocalReranker()
        reranker._model = mock_model  # skip lazy load
        docs = ["a", "b", "c"]
        result = reranker.rerank("q", docs, top_n=2)
        # Should fall back to noop: original order
        assert len(result) == 2
        assert result[0]["index"] == 0
        assert result[1]["index"] == 1


class TestGetRerankerFactory:
    def test_get_reranker_none(self):
        r = get_reranker("none")
        assert isinstance(r, NoopReranker)

    def test_get_reranker_api(self):
        r = get_reranker("api")
        assert isinstance(r, APIReranker)

    @patch("xiaopaw.knowledge.reranker.LocalReranker._ensure_model")
    def test_get_reranker_local(self, mock_ensure):
        r = get_reranker("local")
        assert isinstance(r, LocalReranker)

    def test_get_reranker_unknown(self):
        r = get_reranker("unknown_backend")
        assert isinstance(r, NoopReranker)

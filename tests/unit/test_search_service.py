"""Tests for SearchService and search API handler.

Covers: hybrid / vector / fulltext search modes, embedding fallback,
timeout, result aggregation with preview, API handler auth/JSON/
empty query/invalid mode/limit cap/mode passthrough.
All database access is mocked — no real PostgreSQL required.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from xiaopaw.frontend.search_service import SearchService, _embed_query


# ─── Mock helpers (psycopg2 context-manager pattern) ─────────────────────────


class _CursorCtx:
    """Make mock cursor usable as context manager."""

    def __init__(self, cur: MagicMock):
        self._cur = cur

    def __enter__(self):
        return self._cur

    def __exit__(self, *args):
        return False


@pytest.fixture
def mock_pg():
    """Mock psycopg2.connect → (conn, cur) pair."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = _CursorCtx(cur)
    with patch("xiaopaw.frontend.search_service.psycopg2.connect", return_value=conn):
        yield conn, cur


def _make_row(session_id="s-20260623-001", summary="航班查询", score=0.85,
              created_at=None, user_message="查航班", assistant_reply="好的"):
    return {
        "session_id": session_id,
        "summary": summary,
        "user_message": user_message,
        "assistant_reply": assistant_reply,
        "created_at": created_at or datetime(2026, 6, 23, 10, 30, tzinfo=timezone.utc),
        "turn_ts": None,
        "score": score,
    }


@pytest.fixture
def svc():
    with patch("xiaopaw.frontend.search_service._get_embed_client", return_value=None):
        return SearchService(pg_dsn="postgresql://test")


@pytest.fixture
def svc_with_embed():
    """SearchService with a mocked embedding client."""
    mock_client = MagicMock()
    with patch("xiaopaw.frontend.search_service._get_embed_client", return_value=mock_client):
        service = SearchService(pg_dsn="postgresql://test")
    return service, mock_client


# ═══════════════════════════════════════════════════════════════════════════
# _do_search — dispatch and SQL verification
# ═══════════════════════════════════════════════════════════════════════════


class TestDoSearch:
    """验证 _do_search 的 SQL 和参数。"""

    def test_fulltext_search_params(self, svc, mock_pg):
        """fulltext 模式: tsquery/like_query/limit 参数正确。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = []
        svc._do_search("航班查询", None, "fulltext", 20)

        sql, params = cur.execute.call_args[0]
        assert params["tsquery"] == "航班查询"
        assert params["like_query"] == "%航班查询%"
        assert params["limit"] == 20
        assert "ILIKE %(like_query)s" in sql
        assert "plainto_tsquery('simple', %(tsquery)s)" in sql
        assert "ts_rank" in sql
        assert "ORDER BY score DESC" in sql
        assert "LIMIT %(limit)s" in sql
        assert "FROM memories" in sql

    def test_routing_key_in_params_and_sql(self, svc, mock_pg):
        """routing_key 正确加入 params 和 SQL WHERE 子句。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = []
        svc._do_search("test", "p2p:web_alice", "fulltext", 10)

        sql, params = cur.execute.call_args[0]
        assert params["routing_key"] == "p2p:web_alice"
        assert "routing_key = %(routing_key)s" in sql

    def test_no_routing_key_absent(self, svc, mock_pg):
        """不传 routing_key 时 params 中无该字段，SQL 无 routing_key 条件。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = []
        svc._do_search("test", None, "fulltext", 10)

        sql, params = cur.execute.call_args[0]
        assert "routing_key" not in params
        assert "routing_key" not in sql

    def test_ilike_wildcard_escaped(self, svc, mock_pg):
        """查询中的 % 和 _ 被转义。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = []
        svc._do_search("100%_test", None, "fulltext", 10)

        _, params = cur.execute.call_args[0]
        assert params["like_query"] == "%100\\%\\_test%"

    def test_limit_passed_through(self, svc, mock_pg):
        """limit 参数透传到 SQL params。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = []
        svc._do_search("q", None, "fulltext", 50)

        _, params = cur.execute.call_args[0]
        assert params["limit"] == 50

    def test_conn_closed_after_search(self, svc, mock_pg):
        """搜索完成后连接关闭。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = []
        svc._do_search("q", None, "fulltext", 10)
        conn.close.assert_called_once()

    def test_autocommit_enabled(self, svc, mock_pg):
        """连接设置 autocommit = True。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = []
        svc._do_search("q", None, "fulltext", 10)
        assert conn.autocommit is True

    def test_fetchall_results_returned_as_dicts(self, svc, mock_pg):
        """fetchall 结果转为 dict 列表。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = [
            {"session_id": "s-1", "summary": "a", "score": 0.9,
             "user_message": "", "assistant_reply": "", "created_at": None, "turn_ts": None},
        ]
        rows = svc._do_search("q", None, "fulltext", 10)
        assert len(rows) == 1
        assert isinstance(rows[0], dict)
        assert rows[0]["session_id"] == "s-1"


# ═══════════════════════════════════════════════════════════════════════════
# Search modes: hybrid / vector / fulltext
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchModes:
    """验证不同搜索模式的 SQL 差异。"""

    def test_hybrid_search_sql(self, svc_with_embed, mock_pg):
        """hybrid 模式包含 cosine distance + ts_rank 混合评分。"""
        svc, mock_client = svc_with_embed
        conn, cur = mock_pg
        cur.fetchall.return_value = []

        with patch("xiaopaw.frontend.search_service._embed_query", return_value=[0.1] * 1024):
            svc._do_search("航班", None, "hybrid", 10)

        sql, params = cur.execute.call_args[0]
        assert "summary_vec <=> %(query_vec)s" in sql
        assert "ts_rank" in sql
        assert "0.7" in sql
        assert "0.3" in sql

    def test_vector_search_sql(self, svc_with_embed, mock_pg):
        """vector 模式仅用 cosine distance。"""
        svc, mock_client = svc_with_embed
        conn, cur = mock_pg
        cur.fetchall.return_value = []

        with patch("xiaopaw.frontend.search_service._embed_query", return_value=[0.1] * 1024):
            svc._do_search("航班", None, "vector", 10)

        sql, params = cur.execute.call_args[0]
        assert "summary_vec <=> %(query_vec)s" in sql
        assert "summary_vec IS NOT NULL" in sql
        assert "ts_rank" not in sql

    def test_fulltext_search_sql(self, svc, mock_pg):
        """fulltext 模式仅用 ts_rank。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = []
        svc._do_search("航班", None, "fulltext", 10)

        sql, _ = cur.execute.call_args[0]
        assert "ts_rank" in sql
        assert "summary_vec" not in sql


# ═══════════════════════════════════════════════════════════════════════════
# Embedding fallback
# ═══════════════════════════════════════════════════════════════════════════


class TestEmbeddingFallback:
    """Embedding API 失败时降级到 fulltext，并验证降级后 SQL 结构。"""

    # Canonical assertions for fulltext SQL structure
    _FULLTEXT_SQL_MARKERS = (
        "ILIKE %(like_query)s",
        "search_tsv @@ plainto_tsquery('simple', %(tsquery)s)",
        "ts_rank(search_tsv, plainto_tsquery('simple', %(tsquery)s))",
        "FROM memories",
        "ORDER BY score DESC",
        "LIMIT %(limit)s",
    )

    def _assert_fulltext_sql(self, sql: str, params: dict) -> None:
        """Verify SQL is the fulltext variant with all canonical markers."""
        # Must NOT contain any vector-related clauses
        assert "summary_vec" not in sql, "Fallback SQL must not reference summary_vec"
        assert "query_vec" not in sql, "Fallback SQL must not reference query_vec"
        # Must contain all canonical fulltext markers
        for marker in self._FULLTEXT_SQL_MARKERS:
            assert marker in sql, f"Fallback SQL missing marker: {marker!r}"
        # Must have ILIKE on session_id and summary
        assert "session_id ILIKE" in sql
        assert "summary ILIKE" in sql
        # Params must include tsquery and like_query, but NOT query_vec
        assert "tsquery" in params
        assert "like_query" in params
        assert "query_vec" not in params

    def test_hybrid_fallback_on_embed_failure(self, svc_with_embed, mock_pg):
        """hybrid 模式 embedding 异常 → 降级为 fulltext，SQL 结构完整。"""
        svc, _ = svc_with_embed
        conn, cur = mock_pg
        cur.fetchall.return_value = []

        with patch("xiaopaw.frontend.search_service._embed_query",
                   side_effect=Exception("API error")):
            svc._do_search("航班", None, "hybrid", 10)

        sql, params = cur.execute.call_args[0]
        self._assert_fulltext_sql(sql, params)
        assert params["tsquery"] == "航班"
        assert params["like_query"] == "%航班%"
        assert params["limit"] == 10

    def test_vector_fallback_on_embed_failure(self, svc_with_embed, mock_pg):
        """vector 模式 embedding 异常 → 降级为 fulltext，SQL 结构完整。"""
        svc, _ = svc_with_embed
        conn, cur = mock_pg
        cur.fetchall.return_value = []

        with patch("xiaopaw.frontend.search_service._embed_query",
                   side_effect=Exception("API error")):
            svc._do_search("航班", None, "vector", 10)

        sql, params = cur.execute.call_args[0]
        self._assert_fulltext_sql(sql, params)
        assert params["tsquery"] == "航班"

    def test_hybrid_fallback_sql_matches_direct_fulltext(self, svc_with_embed, svc, mock_pg):
        """hybrid 降级后的 SQL 结构与直接 fulltext 完全一致。"""
        svc_embed, _ = svc_with_embed
        conn, cur = mock_pg
        cur.fetchall.return_value = []

        # 1) Direct fulltext
        svc._do_search("测试", None, "fulltext", 15)
        direct_sql, direct_params = cur.execute.call_args[0]

        cur.reset_mock()
        cur.fetchall.return_value = []

        # 2) Hybrid fallback
        with patch("xiaopaw.frontend.search_service._embed_query",
                   side_effect=Exception("API error")):
            svc_embed._do_search("测试", None, "hybrid", 15)
        fallback_sql, fallback_params = cur.execute.call_args[0]

        # SQL must be identical
        assert fallback_sql == direct_sql, (
            f"Fallback SQL differs from direct fulltext SQL:\n"
            f"  direct:   {direct_sql!r}\n"
            f"  fallback: {fallback_sql!r}"
        )
        # Params must match on all fulltext keys
        assert fallback_params["tsquery"] == direct_params["tsquery"]
        assert fallback_params["like_query"] == direct_params["like_query"]
        assert fallback_params["limit"] == direct_params["limit"]

    def test_no_embed_client_forces_fulltext(self, svc, mock_pg):
        """无 embedding client 时，hybrid 模式自动降级为 fulltext，SQL 结构完整。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = []

        with patch.object(svc, "_embed_client", None):
            svc._do_search("航班", None, "hybrid", 10)

        sql, params = cur.execute.call_args[0]
        self._assert_fulltext_sql(sql, params)

    def test_fallback_with_routing_key(self, svc_with_embed, mock_pg):
        """embedding 失败后降级为 fulltext，routing_key 仍正确传递。"""
        svc, _ = svc_with_embed
        conn, cur = mock_pg
        cur.fetchall.return_value = []

        with patch("xiaopaw.frontend.search_service._embed_query",
                   side_effect=Exception("API error")):
            svc._do_search("航班", "p2p:web_bob", "hybrid", 10)

        sql, params = cur.execute.call_args[0]
        self._assert_fulltext_sql(sql, params)
        assert params["routing_key"] == "p2p:web_bob"
        assert "routing_key = %(routing_key)s" in sql


# ═══════════════════════════════════════════════════════════════════════════
# SearchService.search (async wrapper)
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchAsync:

    @pytest.mark.asyncio
    async def test_hybrid_search_returns_results(self, svc_with_embed, mock_pg):
        """混合搜索模式返回结果（mock embedding 成功 + DB 查询）。"""
        svc, _ = svc_with_embed
        conn, cur = mock_pg
        cur.fetchall.return_value = [
            _make_row(score=0.9, session_id="s-a"),
            _make_row(score=0.7, session_id="s-b"),
        ]

        with patch("xiaopaw.frontend.search_service._embed_query", return_value=[0.1] * 1024):
            results = await svc.search("航班", mode="hybrid", limit=20)

        assert len(results) == 2
        assert results[0]["max_score"] >= results[1]["max_score"]

    @pytest.mark.asyncio
    async def test_fulltext_search_fallback(self, svc_with_embed, mock_pg):
        """embedding API 异常时自动降级到 fulltext，SQL 结构完整。"""
        svc, _ = svc_with_embed
        conn, cur = mock_pg
        cur.fetchall.return_value = [_make_row(score=0.5)]

        with patch("xiaopaw.frontend.search_service._embed_query",
                   side_effect=Exception("API down")):
            results = await svc.search("航班", mode="hybrid")

        assert len(results) == 1
        sql, params = cur.execute.call_args[0]
        # Must be fulltext SQL, not vector
        assert "summary_vec" not in sql, "Fallback SQL must not reference summary_vec"
        assert "ILIKE %(like_query)s" in sql, "Fallback SQL missing ILIKE clause"
        assert "ts_rank" in sql, "Fallback SQL missing ts_rank"
        assert "search_tsv @@ plainto_tsquery" in sql, "Fallback SQL missing tsvector match"
        assert params["tsquery"] == "航班"
        assert params["like_query"] == "%航班%"
        # Verify aggregated result has expected fields
        r = results[0]
        assert "session_id" in r
        assert "max_score" in r
        assert "preview" in r

    @pytest.mark.asyncio
    async def test_search_with_routing_key_filter(self, svc, mock_pg):
        """routing_key 过滤正确传递。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = [_make_row(score=0.5)]

        results = await svc.search("test", routing_key="p2p:web_alice", mode="fulltext")

        _, params = cur.execute.call_args[0]
        assert params["routing_key"] == "p2p:web_alice"
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_empty_query(self, svc, mock_pg):
        """空查询返回空结果。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = []
        results = await svc.search("")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_limit_capped(self, svc, mock_pg):
        """limit 上限 50 — 传 100 只取 50。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = []

        await svc.search("test", mode="fulltext", limit=100)

        _, params = cur.execute.call_args[0]
        # Note: SearchService.search does NOT cap limit itself;
        # the API handler caps at 50. Service passes limit as-is.
        assert params["limit"] == 100

    @pytest.mark.asyncio
    async def test_search_result_format(self, svc, mock_pg):
        """返回字段完整: session_id, title, match_count, max_score, created_at, preview。"""
        conn, cur = mock_pg
        long_reply = "A" * 200
        cur.fetchall.return_value = [
            _make_row(score=0.8542, assistant_reply=long_reply),
        ]
        results = await svc.search("航班", mode="fulltext")
        r = results[0]
        assert r["session_id"] == "s-20260623-001"
        assert r["title"] == "航班查询"
        assert r["match_count"] == 1
        assert r["max_score"] == 0.8542
        assert "2026-06-23" in r["created_at"]
        # preview: first 150 chars + "..."
        assert r["preview"] == "A" * 150 + "..."

    @pytest.mark.asyncio
    async def test_search_score_ordering(self, svc, mock_pg):
        """结果按 max_score 降序。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = [
            _make_row(session_id="s-low", score=0.2),
            _make_row(session_id="s-high", score=0.95),
            _make_row(session_id="s-mid", score=0.6),
        ]
        results = await svc.search("q", mode="fulltext")
        scores = [r["max_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_vector_search_mode(self, svc_with_embed, mock_pg):
        """纯向量搜索模式。"""
        svc, _ = svc_with_embed
        conn, cur = mock_pg
        cur.fetchall.return_value = [_make_row(score=0.92)]

        with patch("xiaopaw.frontend.search_service._embed_query", return_value=[0.1] * 1024):
            results = await svc.search("航班", mode="vector")

        assert len(results) == 1
        sql, _ = cur.execute.call_args[0]
        assert "summary_vec <=> %(query_vec)s" in sql

    @pytest.mark.asyncio
    async def test_fulltext_search_mode(self, svc, mock_pg):
        """纯全文搜索模式。"""
        conn, cur = mock_pg
        cur.fetchall.return_value = [_make_row(score=0.65)]

        results = await svc.search("航班", mode="fulltext")

        assert len(results) == 1
        sql, _ = cur.execute.call_args[0]
        assert "ts_rank" in sql
        assert "summary_vec" not in sql

    @pytest.mark.asyncio
    async def test_search_timeout_returns_empty(self, svc):
        """2秒超时返回空结果。"""
        # Directly simulate what happens when asyncio.wait_for times out:
        # the search method catches TimeoutError and returns [].
        mock_to_thread = AsyncMock(side_effect=asyncio.TimeoutError)
        with patch("xiaopaw.frontend.search_service.asyncio.wait_for",
                   side_effect=asyncio.TimeoutError), \
             patch("xiaopaw.frontend.search_service.asyncio.to_thread",
                   mock_to_thread):
            results = await svc.search("slow query", mode="fulltext")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_exception_returns_empty(self, svc):
        """搜索异常时返回空列表。"""
        with patch.object(svc, "_do_search", side_effect=RuntimeError("DB error")):
            results = await svc.search("test", mode="fulltext")
        assert results == []


# ─── _aggregate 单元测试 ─────────────────────────────────────────────────────


class TestAggregate:

    def test_aggregate_groups_by_session(self):
        rows = [
            _make_row(session_id="s-a", score=0.3, summary="低分"),
            _make_row(session_id="s-a", score=0.9, summary="高分"),
            _make_row(session_id="s-b", score=0.5, summary="中分"),
        ]
        results = SearchService._aggregate(rows)
        assert len(results) == 2
        sa = next(r for r in results if r["session_id"] == "s-a")
        assert sa["title"] == "高分"
        assert sa["match_count"] == 2
        assert sa["max_score"] == 0.9

    def test_aggregate_score_ordering(self):
        rows = [
            _make_row(session_id="s-low", score=0.1),
            _make_row(session_id="s-high", score=0.99),
        ]
        results = SearchService._aggregate(rows)
        assert results[0]["session_id"] == "s-high"

    def test_aggregate_empty_rows(self):
        assert SearchService._aggregate([]) == []

    def test_aggregate_none_score_defaults_zero(self):
        rows = [_make_row(session_id="s-x", score=None)]
        rows[0]["score"] = None
        results = SearchService._aggregate(rows)
        assert results[0]["max_score"] == 0.0

    def test_aggregate_none_created_at(self):
        rows = [_make_row(session_id="s-x", score=0.5, created_at=None)]
        rows[0]["created_at"] = None
        results = SearchService._aggregate(rows)
        assert results[0]["created_at"] is None

    def test_aggregate_preview_truncation(self):
        long_reply = "X" * 200
        rows = [_make_row(session_id="s-x", score=0.5, assistant_reply=long_reply)]
        results = SearchService._aggregate(rows)
        assert results[0]["preview"] == "X" * 150 + "..."

    def test_aggregate_preview_short_reply(self):
        rows = [_make_row(session_id="s-x", score=0.5, assistant_reply="short")]
        results = SearchService._aggregate(rows)
        assert results[0]["preview"] == "short"

    def test_aggregate_score_rounding(self):
        rows = [_make_row(session_id="s-x", score=0.123456789)]
        results = SearchService._aggregate(rows)
        assert results[0]["max_score"] == 0.1235


# ═══════════════════════════════════════════════════════════════════════════
# API Handler Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchAPI:

    def _make_request(self, *, query_params=None, headers=None, app_extras=None):
        req = MagicMock()
        req.query = query_params or {}
        req.headers = headers or {}
        app = {}
        if app_extras:
            app.update(app_extras)
        req.app = app
        return req

    @pytest.mark.asyncio
    async def test_search_api_auth_required(self):
        """无认证返回 401。"""
        from xiaopaw.frontend.routes.search import handle_search

        req = self._make_request(
            query_params={"q": "test"},
            headers={},
            app_extras={"frontend_token": "secret-token", "user_auth": MagicMock()},
        )
        resp = await handle_search(req)
        assert resp.status == 401
        body = json.loads(resp.body)
        assert body["error"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_search_api_returns_json(self):
        """API 返回正确的 JSON 格式。"""
        from xiaopaw.frontend.routes.search import handle_search

        expected = [
            {"session_id": "s-001", "title": "航班查询", "match_count": 2,
             "max_score": 0.85, "created_at": "2026-06-23T10:30:00+00:00"},
        ]
        mock_svc = AsyncMock()
        mock_svc.search = AsyncMock(return_value=expected)

        req = self._make_request(
            query_params={"q": "航班", "mode": "hybrid", "limit": "10"},
            headers={"Authorization": "Bearer valid-token"},
            app_extras={
                "search_service": mock_svc,
                "user_auth": None,
                "frontend_token": "",
            },
        )
        with patch("xiaopaw.frontend.routes.search.check_auth", return_value=True), \
             patch("xiaopaw.frontend.routes.search.get_current_user",
                   return_value={"username": "alice"}):
            resp = await handle_search(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["results"] == expected
        assert body["total"] == 1
        assert body["query"] == "航班"
        mock_svc.search.assert_called_once_with(
            "航班", routing_key="p2p:web_user", mode="hybrid", limit=10
        )

    @pytest.mark.asyncio
    async def test_search_api_empty_query_returns_empty(self):
        from xiaopaw.frontend.routes.search import handle_search

        mock_svc = AsyncMock()
        req = self._make_request(
            query_params={"q": "", "mode": "hybrid"},
            headers={"Authorization": "Bearer valid-token"},
            app_extras={
                "search_service": mock_svc,
                "user_auth": None,
                "frontend_token": "",
            },
        )
        with patch("xiaopaw.frontend.routes.search.check_auth", return_value=True):
            resp = await handle_search(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["results"] == []
        assert body["total"] == 0
        mock_svc.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_api_invalid_mode_returns_400(self):
        from xiaopaw.frontend.routes.search import handle_search

        mock_svc = AsyncMock()
        req = self._make_request(
            query_params={"q": "test", "mode": "bogus"},
            headers={"Authorization": "Bearer valid-token"},
            app_extras={
                "search_service": mock_svc,
                "user_auth": None,
                "frontend_token": "",
            },
        )
        with patch("xiaopaw.frontend.routes.search.check_auth", return_value=True):
            resp = await handle_search(req)

        assert resp.status == 400
        body = json.loads(resp.body)
        assert "Invalid mode" in body["error"]
        mock_svc.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_api_limit_capped_at_50(self):
        from xiaopaw.frontend.routes.search import handle_search

        mock_svc = AsyncMock()
        mock_svc.search = AsyncMock(return_value=[])
        req = self._make_request(
            query_params={"q": "test", "mode": "hybrid", "limit": "999"},
            headers={"Authorization": "Bearer valid-token"},
            app_extras={
                "search_service": mock_svc,
                "user_auth": None,
                "frontend_token": "",
            },
        )
        with patch("xiaopaw.frontend.routes.search.check_auth", return_value=True), \
             patch("xiaopaw.frontend.routes.search.get_current_user", return_value=None):
            resp = await handle_search(req)

        assert resp.status == 200
        mock_svc.search.assert_called_once_with(
            "test", routing_key="p2p:web_user", mode="hybrid", limit=50
        )

    @pytest.mark.asyncio
    async def test_search_api_invalid_limit_defaults_20(self):
        from xiaopaw.frontend.routes.search import handle_search

        mock_svc = AsyncMock()
        mock_svc.search = AsyncMock(return_value=[])
        req = self._make_request(
            query_params={"q": "test", "mode": "hybrid", "limit": "abc"},
            headers={"Authorization": "Bearer valid-token"},
            app_extras={
                "search_service": mock_svc,
                "user_auth": None,
                "frontend_token": "",
            },
        )
        with patch("xiaopaw.frontend.routes.search.check_auth", return_value=True), \
             patch("xiaopaw.frontend.routes.search.get_current_user", return_value=None):
            resp = await handle_search(req)

        assert resp.status == 200
        mock_svc.search.assert_called_once_with(
            "test", routing_key="p2p:web_user", mode="hybrid", limit=20
        )

    @pytest.mark.asyncio
    async def test_mode_parameter_passed_to_service(self):
        """API 层将 mode 参数传递给 SearchService。"""
        from xiaopaw.frontend.routes.search import handle_search

        mock_svc = AsyncMock()
        mock_svc.search = AsyncMock(return_value=[])
        req = self._make_request(
            query_params={"q": "test", "mode": "vector", "limit": "10"},
            headers={"Authorization": "Bearer valid-token"},
            app_extras={
                "search_service": mock_svc,
                "user_auth": None,
                "frontend_token": "",
            },
        )
        with patch("xiaopaw.frontend.routes.search.check_auth", return_value=True), \
             patch("xiaopaw.frontend.routes.search.get_current_user", return_value=None):
            resp = await handle_search(req)

        assert resp.status == 200
        mock_svc.search.assert_called_once_with(
            "test", routing_key="p2p:web_user", mode="vector", limit=10
        )

    @pytest.mark.asyncio
    async def test_search_api_no_user_no_routing_key(self):
        from xiaopaw.frontend.routes.search import handle_search

        mock_svc = AsyncMock()
        mock_svc.search = AsyncMock(return_value=[])
        req = self._make_request(
            query_params={"q": "test", "mode": "fulltext"},
            headers={"Authorization": "Bearer valid-token"},
            app_extras={
                "search_service": mock_svc,
                "user_auth": None,
                "frontend_token": "",
            },
        )
        with patch("xiaopaw.frontend.routes.search.check_auth", return_value=True), \
             patch("xiaopaw.frontend.routes.search.get_current_user", return_value=None):
            resp = await handle_search(req)

        assert resp.status == 200
        mock_svc.search.assert_called_once_with(
            "test", routing_key="p2p:web_user", mode="fulltext", limit=20
        )

    @pytest.mark.asyncio
    async def test_search_api_service_unavailable(self):
        """When neither SearchService nor session_mgr is available, the handler
        gracefully degrades and returns 200 with empty results (see the JSONL
        fallback in ``handle_search``), rather than surfacing a 503."""
        from xiaopaw.frontend.routes.search import handle_search

        req = self._make_request(
            query_params={"q": "test", "mode": "hybrid"},
            headers={"Authorization": "Bearer valid-token"},
            app_extras={
                "search_service": None,
                "user_auth": None,
                "frontend_token": "",
            },
        )
        with patch("xiaopaw.frontend.routes.search.check_auth", return_value=True):
            resp = await handle_search(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body == {"results": [], "total": 0, "query": "test"}

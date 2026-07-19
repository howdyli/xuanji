"""Global search service: hybrid / vector / fulltext search over memories table."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from functools import cache
from typing import Any

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT = 2.0  # seconds


@cache
def _get_embed_client():
    """Singleton OpenAI-compatible client for embeddings (same pattern as indexer)."""
    try:
        from openai import OpenAI

        api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("QWEN_API_KEY", "")
        base_url = (
            os.environ.get("DEEPSEEK_BASE_URL")
            or os.environ.get("QWEN_BASE_URL", "https://api.deepseek.com/v1")
        )
        if not api_key:
            logger.warning("No embedding API key configured; vector search disabled")
            return None
        return OpenAI(api_key=api_key, base_url=base_url)
    except ImportError:
        logger.warning("openai package not installed; vector search disabled")
        return None


def _embed_query(client, query: str) -> list[float]:
    """Call text-embedding-v3 to vectorize *query*."""
    resp = client.embeddings.create(
        model="text-embedding-v3",
        input=[query],
        dimensions=1024,
    )
    return resp.data[0].embedding


class SearchService:
    """Hybrid / vector / fulltext search over the ``memories`` table.

    - ``hybrid``:   0.7 * (1 - cosine_distance) + 0.3 * ts_rank
    - ``vector``:   1 - cosine_distance  (summary_vec only)
    - ``fulltext``: ts_rank over search_tsv
    """

    def __init__(self, pg_dsn: str):
        self._pg_dsn = pg_dsn
        # Pre-check embedding availability
        self._embed_client = _get_embed_client()

    # ------------------------------------------------------------------
    # Public async entry point
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        routing_key: str | None = None,
        mode: str = "hybrid",
        limit: int = 20,
    ) -> list[dict]:
        """Search session memories with timeout protection.

        Returns grouped results sorted by max_score descending.
        """
        # If no embedding client, force fulltext for hybrid/vector
        effective_mode = mode
        if mode in ("hybrid", "vector") and self._embed_client is None:
            logger.warning("Embedding client unavailable; falling back to fulltext")
            effective_mode = "fulltext"

        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(
                    self._do_search, query, routing_key, effective_mode, limit
                ),
                timeout=_SEARCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Search timed out (%ss) for query=%r mode=%s",
                _SEARCH_TIMEOUT,
                query,
                effective_mode,
            )
            return []
        except Exception:
            logger.exception("Search failed for query=%r mode=%s", query, effective_mode)
            return []

        return self._aggregate(results)

    # ------------------------------------------------------------------
    # Synchronous search dispatcher (runs in thread)
    # ------------------------------------------------------------------

    def _do_search(
        self,
        query: str,
        routing_key: str | None,
        mode: str,
        limit: int,
    ) -> list[dict]:
        """Execute the actual search; embedding failures fall back to fulltext."""
        if mode in ("hybrid", "vector"):
            try:
                query_vec = _embed_query(self._embed_client, query)
            except Exception:
                logger.warning(
                    "Embedding API failed for query=%r; falling back to fulltext",
                    query,
                )
                mode = "fulltext"
                query_vec = None
        else:
            query_vec = None

        if mode == "hybrid":
            return self._search_hybrid(query, query_vec, routing_key, limit)
        elif mode == "vector":
            return self._search_vector(query_vec, routing_key, limit)
        else:
            return self._search_fulltext(query, routing_key, limit)

    # ------------------------------------------------------------------
    # SQL search implementations
    # ------------------------------------------------------------------

    def _connect(self):
        conn = psycopg2.connect(self._pg_dsn)
        conn.autocommit = True
        return conn

    def _search_hybrid(
        self,
        query: str,
        query_vec: list[float],
        routing_key: str | None,
        limit: int,
    ) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                params: dict[str, Any] = {
                    "query_vec": str(query_vec),
                    "tsquery": query,
                    "limit": limit,
                }
                where_parts: list[str] = []
                if routing_key:
                    where_parts.append("routing_key = %(routing_key)s")
                    params["routing_key"] = routing_key
                where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

                cur.execute(
                    f"""
                    SELECT session_id, summary, user_message,
                           assistant_reply, created_at, turn_ts,
                           0.7 * (1 - (summary_vec <=> %(query_vec)s::vector))
                           + 0.3 * ts_rank(search_tsv, plainto_tsquery('simple', %(tsquery)s))
                           AS score
                    FROM memories
                    {where_sql}
                    ORDER BY score DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def _search_vector(
        self,
        query_vec: list[float],
        routing_key: str | None,
        limit: int,
    ) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                params: dict[str, Any] = {
                    "query_vec": str(query_vec),
                    "limit": limit,
                }
                where_parts = ["summary_vec IS NOT NULL"]
                if routing_key:
                    where_parts.append("routing_key = %(routing_key)s")
                    params["routing_key"] = routing_key
                where_sql = "WHERE " + " AND ".join(where_parts)

                cur.execute(
                    f"""
                    SELECT session_id, summary, user_message,
                           assistant_reply, created_at, turn_ts,
                           (1 - (summary_vec <=> %(query_vec)s::vector)) AS score
                    FROM memories
                    {where_sql}
                    ORDER BY score DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def _search_fulltext(
        self,
        query: str,
        routing_key: str | None,
        limit: int,
    ) -> list[dict]:
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Escape ILIKE wildcards in user input
                escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                params: dict[str, Any] = {
                    "tsquery": query,
                    "like_query": f"%{escaped_query}%",
                    "limit": limit,
                }
                where_parts = [
                    "("
                    + " OR ".join([
                        "session_id ILIKE %(like_query)s ESCAPE '\\'",
                        "summary ILIKE %(like_query)s ESCAPE '\\'",
                        "search_tsv @@ plainto_tsquery('simple', %(tsquery)s)",
                    ])
                    + ")"
                ]
                if routing_key:
                    where_parts.append("routing_key = %(routing_key)s")
                    params["routing_key"] = routing_key
                where_sql = "WHERE " + " AND ".join(where_parts)

                cur.execute(
                    f"""
                    SELECT session_id, summary, user_message,
                           assistant_reply, created_at, turn_ts,
                           ts_rank(search_tsv, plainto_tsquery('simple', %(tsquery)s)) AS score
                    FROM memories
                    {where_sql}
                    ORDER BY score DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Result aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate(rows: list[dict]) -> list[dict]:
        """Group by session_id with preview, score rounding, and best-title pick.

        Returns:
            [{session_id, title, match_count, max_score, created_at, preview}, ...]
            sorted by max_score descending.
        """
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            groups[row["session_id"]].append(row)

        results = []
        for session_id, items in groups.items():
            best = max(items, key=lambda r: r.get("score", 0))
            score = round(float(best["score"]), 4) if best.get("score") is not None else 0.0
            created_at = best.get("created_at")

            # Build preview from assistant_reply (first 150 chars, truncated)
            reply = best.get("assistant_reply") or ""
            preview = reply[:150] + "..." if len(reply) > 150 else reply

            results.append({
                "session_id": session_id,
                "title": best.get("summary") or "",
                "match_count": len(items),
                "max_score": score,
                "created_at": created_at.isoformat() if created_at else None,
                "preview": preview,
            })

        results.sort(key=lambda r: r["max_score"], reverse=True)
        return results

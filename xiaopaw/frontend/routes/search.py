"""Search route handler: GET /api/frontend/search"""

from __future__ import annotations

import logging

from aiohttp import web

from xiaopaw.frontend.routes.helpers import check_auth, get_current_user, get_routing_key_from_request

logger = logging.getLogger(__name__)

_VALID_MODES = {"hybrid", "fulltext", "vector"}


async def handle_search(request: web.Request) -> web.StreamResponse:
    """GET /api/frontend/search?q=xxx&mode=hybrid|fulltext|vector&limit=20"""
    # 1. Auth
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    # 2. Parameters
    q = request.query.get("q", "").strip()
    mode = request.query.get("mode", "hybrid")
    try:
        limit = min(int(request.query.get("limit", "20")), 50)
    except (ValueError, TypeError):
        limit = 20

    if not q:
        return web.json_response({"results": [], "total": 0, "query": ""})

    if mode not in _VALID_MODES:
        return web.json_response(
            {"error": f"Invalid mode: {mode!r}. Use hybrid, fulltext, or vector."},
            status=400,
        )

    # 3. Build routing_key for user isolation
    routing_key = get_routing_key_from_request(request)

    # 4. Execute search via SearchService (PostgreSQL full-text/vector) when available
    search_service = request.app.get("search_service")
    if search_service is not None:
        try:
            results = await search_service.search(
                q, routing_key=routing_key, mode=mode, limit=limit
            )
            if results:
                return web.json_response(
                    {"results": results, "total": len(results), "query": q}
                )
        except Exception:
            logger.exception("Search failed for query=%r, trying JSONL fallback", q)

    # 5. Fallback: keyword search over JSONL history when PG is unavailable or empty
    session_mgr = request.app.get("session_mgr")
    if session_mgr is not None:
        try:
            results = await _jsonl_keyword_search(session_mgr, routing_key, q, limit)
            return web.json_response(
                {"results": results, "total": len(results), "query": q}
            )
        except Exception:
            logger.exception("JSONL fallback search failed for query=%r", q)

    return web.json_response({"results": [], "total": 0, "query": q})


def _build_preview(content: str, needle_lower: str, window: int = 40) -> str:
    """Return a snippet of ``content`` centered on the first match of the query."""
    lower = content.lower()
    pos = lower.find(needle_lower)
    if pos < 0:
        return content[: window * 2].strip()
    start = max(0, pos - window)
    end = min(len(content), pos + len(needle_lower) + window)
    snippet = content[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{snippet}{suffix}"


async def _jsonl_keyword_search(
    session_mgr, routing_key: str, q: str, limit: int
) -> list[dict]:
    """Case-insensitive substring search across a user's JSONL session history.

    Produces the same result shape as SearchService so the frontend renders it
    identically: {session_id, title, match_count, max_score, created_at, preview}.
    """
    needle = q.lower()
    results: list[dict] = []
    for meta in session_mgr.list_all_sessions():
        # User isolation: only this user's sessions (plus legacy anonymous ones).
        rk = meta.get("routing_key")
        if rk != routing_key and rk != "p2p:web_user":
            continue
        entries = await session_mgr.load_history(meta["id"], max_turns=10000)
        match_count = 0
        preview = ""
        for e in entries:
            content = e.content or ""
            if needle in content.lower():
                match_count += 1
                if not preview:
                    preview = _build_preview(content, needle)
        if match_count:
            results.append({
                "session_id": meta["id"],
                "title": meta.get("title") or f"会话 {meta['id'][:8]}",
                "match_count": match_count,
                "max_score": float(match_count),
                "created_at": meta.get("updated_at") or "",
                "preview": preview,
            })
    results.sort(key=lambda r: r["match_count"], reverse=True)
    return results[:limit]


def register_search_routes(app: web.Application) -> None:
    """Register search routes on the aiohttp application."""
    app.router.add_get("/api/frontend/search", handle_search)

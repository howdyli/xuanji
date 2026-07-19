"""Agent activity polling endpoint for collaboration visualization."""

from __future__ import annotations

import logging

from aiohttp import web

from xiaopaw.frontend.routes.helpers import check_auth

logger = logging.getLogger(__name__)


async def handle_agent_activities(request: web.Request) -> web.Response:
    """GET /api/frontend/sessions/{session_id}/activities

    Query params:
      - mode: 'active' (内存缓冲区) | 'history' (PG 查询)
      - turn_id: optional, filter by turn
      - limit: max results (default 50)
    """
    # 1. Auth
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    # 2. Path param
    session_id = request.match_info["session_id"]

    # 3. Query params
    mode = request.query.get("mode", "active")
    turn_id = request.query.get("turn_id", "")
    try:
        limit = min(int(request.query.get("limit", "50")), 200)
    except (ValueError, TypeError):
        limit = 50

    if mode not in ("active", "history"):
        return web.json_response(
            {"error": f"Invalid mode: {mode!r}. Use 'active' or 'history'."},
            status=400,
        )

    # 4. ActivityRecorder
    recorder = request.app.get("activity_recorder")
    if recorder is None:
        return web.json_response({"error": "activity recorder not available"}, status=503)

    # 5. Fetch activities
    try:
        if mode == "active":
            activities = recorder.get_active(session_id)
        else:
            activities = recorder.get_history(session_id, turn_id=turn_id, limit=limit)
    except Exception:
        logger.exception("Failed to fetch activities for session=%s", session_id)
        return web.json_response({"error": "failed to fetch activities"}, status=500)

    return web.json_response({"activities": activities})


def register_activity_routes(app: web.Application) -> None:
    """Register activity polling routes on the aiohttp application."""
    app.router.add_get(
        "/api/frontend/sessions/{session_id}/activities",
        handle_agent_activities,
    )

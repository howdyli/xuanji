"""Session and messaging route handlers."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from aiohttp import web

from xiaopaw.api.capture_sender import CaptureSender
from xiaopaw.frontend.routes.helpers import (
    check_auth,
    get_current_user,
    get_routing_key_from_request,
    list_sessions_for_user,
)
from xiaopaw.frontend.store import PGStore
from xiaopaw.models import InboundMessage
from xiaopaw.observability.trace import new_trace_id

logger = logging.getLogger(__name__)


async def handle_message(request: web.Request) -> web.Response:
    """POST /api/frontend/message - send a message to the AI."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        body = await request.json()
        content = body.get("content", "").strip()
        session_id_hint = body.get("session_id", "")
        expert_name = body.get("expert", "").strip()
        if not content:
            return web.json_response({"error": "content is required"}, status=422)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=422)

    # Build routing_key from authenticated user (ignore frontend value)
    routing_key = get_routing_key_from_request(request)
    user = get_current_user(request)
    sender_id = user.get("username") if user else "anonymous"

    runner = request.app.get("runner")
    sender = request.app.get("sender")
    session_mgr = request.app.get("session_mgr")
    pg_store: PGStore | None = request.app.get("pg_store")

    if not runner or not session_mgr:
        return web.json_response({"error": "backend not ready"}, status=503)

    # Activate existing session if session_id_hint provided
    if session_id_hint:
        existing = await session_mgr.get_session_by_id(session_id_hint)
        if existing:
            await session_mgr.activate_session(session_id_hint, routing_key)

    session = await session_mgr.get_or_create(routing_key)
    session_id = session.id

    msg_id = f"web_{uuid.uuid4().hex[:12]}"

    # Inject expert system prompt if specified
    if expert_name:
        expert_reg = request.app.get("expert_registry")
        if expert_reg:
            expert = expert_reg.get(expert_name)
            if expert and expert.get("system_prompt"):
                content = f"[Expert: {expert['display_name']}]\n{expert['system_prompt']}\n\n---\n\n{content}"

    inbound = InboundMessage(
        routing_key=routing_key,
        content=content,
        msg_id=msg_id,
        sender_id=sender_id,
        ts=int(time.time() * 1000),
        trace_id=new_trace_id(),
    )

    # Register a future to capture the AI reply
    future = None
    if isinstance(sender, CaptureSender):
        future = sender.register(msg_id)

    # Dispatch to runner
    start = time.monotonic()
    await runner.dispatch(inbound)

    # Wait for reply (only works with CaptureSender)
    reply = ""
    if future:
        try:
            reply = await future
        except Exception as exc:
            logger.warning("frontend: reply capture failed: %s", exc)
            reply = "[error]"

    duration_ms = int((time.monotonic() - start) * 1000)

    # Persist to PostgreSQL (async, fire-and-forget)
    if pg_store:
        await pg_store.save_conversation(msg_id, session_id, routing_key, "user", content)
        await pg_store.save_conversation(
            f"{msg_id}_reply", session_id, routing_key, "assistant", reply
        )
        await pg_store.save_session(
            session_id, routing_key,
            title=content[:80],
            message_count=session.message_count + 2,
        )

    return web.json_response({
        "msg_id": msg_id,
        "reply": reply,
        "session_id": session_id,
        "duration_ms": duration_ms,
        "trace_id": inbound.trace_id,
    })


async def handle_sessions(request: web.Request) -> web.Response:
    """GET /api/frontend/sessions - list active sessions (personal + team shared)."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    # Try PGStore first (has titles, correct updated_at)
    pg_store: PGStore | None = request.app.get("pg_store")
    if pg_store and pg_store._available:
        try:
            routing_key = get_routing_key_from_request(request)
            sessions = await list_sessions_for_user(pg_store, routing_key)

            # Merge team shared sessions
            team_store = request.app.get("team_store")
            user = get_current_user(request)
            if team_store and user:
                team_ids = team_store.get_user_team_ids(user["id"])
                if team_ids:
                    team_sessions = await _list_team_shared_sessions(pg_store, team_ids)
                    # Deduplicate by id
                    existing_ids = {s["id"] for s in sessions}
                    for ts in team_sessions:
                        if ts["id"] not in existing_ids:
                            ts["is_team_shared"] = True
                            sessions.append(ts)

            if sessions:
                return web.json_response({"sessions": sessions})
        except Exception as exc:
            logger.warning("frontend: failed to fetch sessions from PG: %s", exc)

    # Fallback: list from SessionManager (JSONL-based)
    session_mgr = request.app.get("session_mgr")
    if session_mgr:
        routing_key = get_routing_key_from_request(request)
        all_sessions = session_mgr.list_all_sessions()
        user_sessions = [
            s for s in all_sessions
            if s.get("routing_key") == routing_key or s.get("routing_key") == "p2p:web_user"
        ]
        return web.json_response({"sessions": user_sessions})

    return web.json_response({"sessions": []})


async def _list_team_shared_sessions(pg_store, team_ids: list[int]) -> list[dict]:
    """Query PG for sessions shared with any of the user's teams."""
    try:
        import psycopg2
        import psycopg2.extras
        with psycopg2.connect(pg_store._dsn) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, routing_key, title, message_count, team_id,
                              shared_by, share_permission, created_at, updated_at
                       FROM sessions WHERE team_id = ANY(%s)
                       ORDER BY updated_at DESC LIMIT 50""",
                    (team_ids,),
                )
                sessions = list(cur.fetchall())
                for s in sessions:
                    for k in ("created_at", "updated_at"):
                        if s.get(k):
                            s[k] = s[k].isoformat()
                return sessions
    except Exception as exc:
        logger.warning("_list_team_shared_sessions failed: %s", exc)
        return []


def _check_team_session_access(request: web.Request, session_id: str) -> bool:
    """Check if current user can access a session via team sharing.

    Returns True if the session is shared with one of the user's teams.
    """
    team_store = request.app.get("team_store")
    user = get_current_user(request)
    pg_store = request.app.get("pg_store")
    if not team_store or not user or not pg_store:
        return False

    team_ids = team_store.get_user_team_ids(user["id"])
    if not team_ids:
        return False

    try:
        import psycopg2
        with psycopg2.connect(pg_store._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT team_id FROM sessions WHERE id = %s AND team_id = ANY(%s)",
                    (session_id, team_ids),
                )
                return cur.fetchone() is not None
    except Exception:
        return False


async def handle_session_messages(request: web.Request) -> web.Response:
    """GET /api/frontend/sessions/{session_id}/messages - get session history."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    session_id = request.match_info.get("session_id", "")
    if not session_id:
        return web.json_response({"error": "missing session_id"}, status=422)

    session_mgr = request.app.get("session_mgr")
    if not session_mgr:
        return web.json_response({"error": "backend not ready"}, status=503)

    # IDOR check: verify session belongs to the current user OR is team-shared
    routing_key = get_routing_key_from_request(request)
    session_entry = await session_mgr.get_session_by_id(session_id)
    if not session_entry:
        # Unknown session id -> 404 (avoids returning an empty 200 that the
        # frontend cannot distinguish from a real, empty conversation).
        return web.json_response({"error": "not found"}, status=404)
    if session_entry:
        # SessionManager._index maps routing_key -> RoutingEntry;
        # find which routing_key owns this session
        owning_rk = None
        for rk, entry in session_mgr._index.items():
            for s in entry.sessions:
                if s.id == session_id:
                    owning_rk = rk
                    break
            if owning_rk:
                break
        if owning_rk and owning_rk != routing_key and owning_rk != "p2p:web_user":
            # Check team sharing access
            team_access = _check_team_session_access(request, session_id)
            if not team_access:
                return web.json_response({"error": "not found"}, status=404)

    try:
        entries = await session_mgr.load_history(session_id)
        messages = []
        for idx, e in enumerate(entries):
            messages.append({
                # Include index so consecutive entries sharing the same
                # millisecond timestamp (e.g. a user msg + its reply) still
                # produce unique ids (prevents duplicate React keys).
                "id": f"{session_id}_{e.ts}_{idx}",
                "role": e.role,
                "content": e.content,
                "timestamp": datetime.fromtimestamp(e.ts / 1000, tz=timezone.utc).isoformat() if e.ts else None,
            })
        return web.json_response({"messages": messages})
    except Exception as exc:
        logger.warning("frontend: load_history failed for %s: %s", session_id, exc)
        return web.json_response({"error": str(exc)}, status=500)


async def handle_create_session(request: web.Request) -> web.Response:
    """POST /api/frontend/sessions - create a new session."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    session_mgr = request.app.get("session_mgr")
    if not session_mgr:
        return web.json_response({"error": "backend not ready"}, status=503)

    routing_key = get_routing_key_from_request(request)
    session = await session_mgr.create_new_session(routing_key)

    return web.json_response({
        "session_id": session.id,
    })


async def handle_config(request: web.Request) -> web.Response:
    """GET /api/frontend/config - get frontend configuration."""
    return web.json_response({
        "app_name": "玄机",
        "version": "2.0.0",
        "features": {
            "chat": True,
            "sessions": True,
            "settings": True,
        },
    })


def register_session_routes(app: web.Application) -> None:
    """Register session and messaging routes."""
    app.router.add_post("/api/frontend/message", handle_message)
    app.router.add_post("/api/frontend/sessions", handle_create_session)
    app.router.add_get("/api/frontend/sessions", handle_sessions)
    app.router.add_get("/api/frontend/sessions/{session_id}/messages", handle_session_messages)
    app.router.add_get("/api/frontend/config", handle_config)

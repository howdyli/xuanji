"""Session and messaging route handlers."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
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

# Typewriter chunking for the streaming endpoint. CrewAI has no token-level
# streaming, so the reply arrives all-at-once; we split it into small chunks
# to produce a progressive "typewriter" render on the client. The same `delta`
# protocol will transparently carry real tokens if token streaming is added.
_STREAM_CHUNK_CHARS = 4
_STREAM_CHUNK_DELAY = 0.012  # seconds between chunks
_STREAM_MAX_ANIMATION = 2.0  # cap total added latency (long replies use bigger chunks)


@dataclass
class _PreparedMessage:
    """Everything a message handler needs after auth/session/inbound setup."""

    runner: object
    sender: object
    session_mgr: object
    pg_store: PGStore | None
    inbound: InboundMessage
    session: object
    session_id: str
    routing_key: str
    user: dict | None
    content: str
    msg_id: str


async def _prepare_message(
    request: web.Request,
) -> tuple[_PreparedMessage | None, web.Response | None]:
    """Shared setup for the one-shot and streaming message endpoints.

    Returns ``(prepared, None)`` on success or ``(None, error_response)`` when
    auth/validation/permission checks fail. Callers own dispatch, reply capture
    and persistence so the two endpoints can differ only in transport.
    """
    if not check_auth(request):
        return None, web.json_response({"error": "unauthorized"}, status=401)

    try:
        body = await request.json()
        content = body.get("content", "").strip()
        session_id_hint = body.get("session_id", "")
        expert_name = body.get("expert", "").strip()
        if not content:
            return None, web.json_response({"error": "content is required"}, status=422)
    except Exception as exc:
        return None, web.json_response({"error": str(exc)}, status=422)

    # Build routing_key from authenticated user (ignore frontend value)
    routing_key = get_routing_key_from_request(request)
    user = get_current_user(request)
    sender_id = user.get("username") if user else "anonymous"

    runner = request.app.get("runner")
    sender = request.app.get("sender")
    session_mgr = request.app.get("session_mgr")
    pg_store: PGStore | None = request.app.get("pg_store")

    if not runner or not session_mgr:
        return None, web.json_response({"error": "backend not ready"}, status=503)

    # Activate existing session if session_id_hint provided.
    # Sessions owned by a *different* routing_key are team-shared: writing to
    # them requires 'edit' permission. 'view' shares are read-only (403) and
    # unknown/foreign sessions are hidden (404) to prevent session hijacking
    # (activate_session would otherwise adopt them into the caller's routing_key).
    if session_id_hint:
        existing = await session_mgr.get_session_by_id(session_id_hint)
        if existing:
            owning_rk = _find_owning_routing_key(session_mgr, session_id_hint)
            if owning_rk and owning_rk != routing_key and owning_rk != "p2p:web_user":
                permission = _resolve_shared_session_permission(request, session_id_hint)
                if permission is None:
                    return None, web.json_response({"error": "not found"}, status=404)
                if permission != "edit":
                    return None, web.json_response(
                        {"error": "read-only: this shared session grants view access only"},
                        status=403,
                    )
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

    return (
        _PreparedMessage(
            runner=runner,
            sender=sender,
            session_mgr=session_mgr,
            pg_store=pg_store,
            inbound=inbound,
            session=session,
            session_id=session_id,
            routing_key=routing_key,
            user=user,
            content=content,
            msg_id=msg_id,
        ),
        None,
    )


async def _persist_exchange(prep: _PreparedMessage, reply: str) -> None:
    """Persist the user message + assistant reply to PostgreSQL (best-effort)."""
    pg_store = prep.pg_store
    if not pg_store:
        return
    await pg_store.save_conversation(
        prep.msg_id, prep.session_id, prep.routing_key, "user", prep.content
    )
    await pg_store.save_conversation(
        f"{prep.msg_id}_reply", prep.session_id, prep.routing_key, "assistant", reply
    )
    await pg_store.save_session(
        prep.session_id, prep.routing_key,
        title=prep.content[:80],
        message_count=prep.session.message_count + 2,
        org_id=prep.user.get("org_id") if prep.user else None,
    )


async def handle_message(request: web.Request) -> web.Response:
    """POST /api/frontend/message - send a message to the AI."""
    prep, err = await _prepare_message(request)
    if err is not None:
        return err
    assert prep is not None

    # Register a future to capture the AI reply
    future = None
    if isinstance(prep.sender, CaptureSender):
        future = prep.sender.register(prep.msg_id)

    # Dispatch to runner
    start = time.monotonic()
    await prep.runner.dispatch(prep.inbound)

    # Wait for reply (only works with CaptureSender)
    reply = ""
    if future:
        try:
            reply = await future
        except Exception as exc:
            logger.warning("frontend: reply capture failed: %s", exc)
            reply = "[error]"

    duration_ms = int((time.monotonic() - start) * 1000)

    await _persist_exchange(prep, reply)

    return web.json_response({
        "msg_id": prep.msg_id,
        "reply": reply,
        "session_id": prep.session_id,
        "duration_ms": duration_ms,
        "trace_id": prep.inbound.trace_id,
    })


def _sse_frame(event: str, data: dict) -> bytes:
    """Format a single SSE frame (matches activity_stream.py wire format)."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _chunk_reply(reply: str) -> list[str]:
    """Split *reply* into typewriter chunks with a bounded animation budget.

    Short replies stream in ~4-char chunks; long replies grow the chunk size so
    total added latency never exceeds ``_STREAM_MAX_ANIMATION``.
    """
    if not reply:
        return []
    max_chunks = max(1, int(_STREAM_MAX_ANIMATION / _STREAM_CHUNK_DELAY))
    chunk_size = max(_STREAM_CHUNK_CHARS, -(-len(reply) // max_chunks))
    return [reply[i:i + chunk_size] for i in range(0, len(reply), chunk_size)]


async def handle_message_stream(request: web.Request) -> web.StreamResponse:
    """POST /api/frontend/message/stream - stream the AI reply via SSE.

    Emits ``start`` -> ``delta``* -> ``done`` frames. Because CrewAI returns the
    reply all-at-once, deltas are server-chunked for a typewriter effect; the
    protocol is forward-compatible with real token streaming. Errors surface as
    an ``error`` frame so the client can classify + reconcile.
    """
    prep, err = await _prepare_message(request)
    if err is not None:
        return err
    assert prep is not None

    future = None
    if isinstance(prep.sender, CaptureSender):
        future = prep.sender.register(prep.msg_id)

    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    start = time.monotonic()
    reply = ""
    try:
        await response.write(_sse_frame("start", {
            "msg_id": prep.msg_id,
            "session_id": prep.session_id,
            "trace_id": prep.inbound.trace_id,
        }))

        await prep.runner.dispatch(prep.inbound)

        if future:
            try:
                reply = await future
            except Exception as exc:
                logger.warning("frontend: reply capture failed: %s", exc)
                reply = "[error]"

        for chunk in _chunk_reply(reply):
            await response.write(_sse_frame("delta", {"text": chunk}))
            if _STREAM_CHUNK_DELAY:
                await asyncio.sleep(_STREAM_CHUNK_DELAY)

        duration_ms = int((time.monotonic() - start) * 1000)
        await response.write(_sse_frame("done", {
            "msg_id": prep.msg_id,
            "reply": reply,
            "session_id": prep.session_id,
            "duration_ms": duration_ms,
            "trace_id": prep.inbound.trace_id,
        }))
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        logger.debug("stream: client disconnected msg_id=%s", prep.msg_id)
    except Exception as exc:
        logger.warning("stream: message stream failed: %s", exc)
        try:
            await response.write(_sse_frame("error", {"message": str(exc)}))
        except Exception:
            pass
    finally:
        # Persist whatever reply we captured (even on client disconnect).
        try:
            await _persist_exchange(prep, reply)
        except Exception as exc:
            logger.warning("stream: persist failed: %s", exc)

    return response


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


def _find_owning_routing_key(session_mgr, session_id: str) -> str | None:
    """Return the routing_key that owns *session_id*, or None if not found."""
    for rk, entry in session_mgr._index.items():
        for s in entry.sessions:
            if s.id == session_id:
                return rk
    return None


def _resolve_shared_session_permission(
    request: web.Request, session_id: str
) -> str | None:
    """Return the current user's share permission for a team-shared session.

    Returns ``"edit"`` or ``"view"`` when *session_id* is shared with one of
    the current user's teams, else ``None`` (no team-shared access). A NULL or
    empty ``share_permission`` column is normalized to the safe default
    ``"view"``.
    """
    team_store = request.app.get("team_store")
    user = get_current_user(request)
    pg_store = request.app.get("pg_store")
    if not team_store or not user or not pg_store:
        return None

    team_ids = team_store.get_user_team_ids(user["id"])
    if not team_ids:
        return None

    try:
        import psycopg2
        with psycopg2.connect(pg_store._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT share_permission, org_id FROM sessions "
                    "WHERE id = %s AND team_id = ANY(%s)",
                    (session_id, team_ids),
                )
                row = cur.fetchone()
                if not row:
                    return None
                # Depth defense (multi-tenant): a shared session must belong to
                # the caller's org. A NULL org (legacy, pre-backfill) is allowed
                # for backward compatibility and does not block access.
                if not _org_visible(row[1], user.get("org_id")):
                    return None
                return row[0] or "view"
    except Exception:
        return None


def _org_visible(session_org: int | None, user_org: int | None) -> bool:
    """Return whether a session's org is visible to a caller's org.

    Multi-tenant depth defense: visible only when both orgs are known and
    equal. A NULL on either side (legacy rows / users pre-backfill) is treated
    as compatible and does not block access.
    """
    if session_org is None or user_org is None:
        return True
    return session_org == user_org


def _check_team_session_access(request: web.Request, session_id: str) -> bool:
    """Check if current user can *read* a session via team sharing.

    Read access is granted to both ``view`` and ``edit`` shares, so this is
    True whenever the session is shared with one of the user's teams.
    """
    return _resolve_shared_session_permission(request, session_id) is not None


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
        # Find which routing_key owns this session; sessions owned by a
        # *different* routing_key are only accessible via team sharing.
        owning_rk = _find_owning_routing_key(session_mgr, session_id)
        if owning_rk and owning_rk != routing_key and owning_rk != "p2p:web_user":
            # Check team sharing access
            if not _check_team_session_access(request, session_id):
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
    app.router.add_post("/api/frontend/message/stream", handle_message_stream)
    app.router.add_post("/api/frontend/sessions", handle_create_session)
    app.router.add_get("/api/frontend/sessions", handle_sessions)
    app.router.add_get("/api/frontend/sessions/{session_id}/messages", handle_session_messages)
    app.router.add_get("/api/frontend/config", handle_config)

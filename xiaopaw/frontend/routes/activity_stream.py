"""SSE (Server-Sent Events) endpoint for real-time Agent activity streaming.

Replaces 2s polling with instant push: EventBus events are forwarded to
connected clients as SSE frames with <50ms latency.

Endpoint: GET /api/frontend/sessions/{session_id}/activities/stream
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from aiohttp import web

from xiaopaw.event_bus import AgentEvent, EventPayload
from xiaopaw.frontend.routes.helpers import check_auth

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

HEARTBEAT_INTERVAL = 15  # seconds between heartbeat comments
CONNECTION_TIMEOUT = 300  # 5 minutes max idle time
MAX_CONNECTIONS_PER_SESSION = 3

# Track active SSE connections per session for concurrency limiting
_active_connections: dict[str, int] = {}


# ── SSE Frame Helpers ────────────────────────────────────────────────────────


def _sse_frame(event: str, data: dict[str, Any]) -> bytes:
    """Format a single SSE frame."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _sse_comment(text: str = "heartbeat") -> bytes:
    """Format an SSE comment (used for keepalive)."""
    return f":{text}\n\n".encode("utf-8")


# ── Activity Serialization ───────────────────────────────────────────────────


def _payload_to_activity(payload: EventPayload) -> dict[str, Any]:
    """Convert an EventPayload to the activity dict format expected by frontend."""
    event_type = payload.event.value if isinstance(payload.event, AgentEvent) else str(payload.event)
    data = payload.data or {}
    return {
        "event_type": event_type,
        "agent_role": data.get("agent_role", ""),
        "tool_name": data.get("tool_name", ""),
        "skill_name": data.get("skill_name", ""),
        "status": (
            "active" if event_type in ("agent_started", "tool_call_start", "thinking")
            else "error" if event_type == "agent_error"
            else "completed"
        ),
        "duration_ms": data.get("duration_ms", 0),
        "metadata": data,
        "created_at": payload.timestamp,
    }


# ── SSE Handler ──────────────────────────────────────────────────────────────


async def handle_activity_stream(request: web.Request) -> web.StreamResponse:
    """GET /api/frontend/sessions/{session_id}/activities/stream

    Establishes an SSE connection that pushes Agent activity events in real-time.
    The connection closes automatically when the agent completes or errors.
    """
    # 1. Auth
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    # 2. Path param
    session_id = request.match_info["session_id"]

    # 3. EventBus availability
    event_bus = request.app.get("event_bus")
    if event_bus is None:
        return web.json_response({"error": "event bus not available"}, status=503)

    # 4. Concurrency limit
    current = _active_connections.get(session_id, 0)
    if current >= MAX_CONNECTIONS_PER_SESSION:
        return web.json_response(
            {"error": "too many SSE connections for this session"},
            status=429,
        )

    # 5. Prepare SSE response
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering if proxied
        },
    )
    await response.prepare(request)

    # 6. Setup event queue and subscription
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=100)
    loop = asyncio.get_event_loop()
    done_event = asyncio.Event()

    def _on_event(payload: EventPayload) -> None:
        """EventBus handler — called from potentially different thread."""
        # Only forward AgentEvent types
        if not isinstance(payload.event, AgentEvent):
            return

        activity = _payload_to_activity(payload)
        event_type = activity["event_type"]

        # Thread-safe enqueue
        try:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "activity", "data": activity})
        except RuntimeError:
            # Loop closed — connection already torn down
            return

        # Terminal events signal connection close
        if event_type in ("agent_complete", "agent_error"):
            try:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "done", "data": {"reason": event_type}},
                )
            except RuntimeError:
                pass

    # Subscribe with session filter
    unsubscribe = event_bus.subscribe("*", _on_event, session_id=session_id)
    _active_connections[session_id] = current + 1

    try:
        # Send initial connection confirmation
        await response.write(_sse_frame("connected", {"session_id": session_id}))

        last_activity_time = time.monotonic()

        while True:
            try:
                # Wait for next event with timeout for heartbeat
                msg = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                # Check idle timeout
                idle_seconds = time.monotonic() - last_activity_time
                if idle_seconds >= CONNECTION_TIMEOUT:
                    await response.write(_sse_frame("timeout", {"reason": "idle_timeout"}))
                    break
                # Send heartbeat
                try:
                    await response.write(_sse_comment())
                except (ConnectionResetError, ConnectionAbortedError):
                    break
                continue

            if msg is None:
                break

            last_activity_time = time.monotonic()

            if msg["type"] == "activity":
                await response.write(_sse_frame("activity", msg["data"]))
            elif msg["type"] == "done":
                await response.write(_sse_frame("done", msg["data"]))
                break

    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        logger.debug("SSE client disconnected: session=%s", session_id[:8])
    except Exception as e:
        logger.warning("SSE stream error: session=%s error=%s", session_id[:8], e)
    finally:
        # Cleanup: unsubscribe and decrement connection count
        unsubscribe()
        _active_connections[session_id] = max(0, _active_connections.get(session_id, 1) - 1)
        if _active_connections[session_id] == 0:
            _active_connections.pop(session_id, None)
        logger.debug("SSE connection closed: session=%s", session_id[:8])

    return response


# ── Route Registration ───────────────────────────────────────────────────────


def register_activity_stream_routes(app: web.Application) -> None:
    """Register SSE activity stream route on the aiohttp application."""
    app.router.add_get(
        "/api/frontend/sessions/{session_id}/activities/stream",
        handle_activity_stream,
    )

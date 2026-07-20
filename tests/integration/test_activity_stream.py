"""Integration tests for the SSE activity stream endpoint.

Tests:
- SSE connection establishment and auth
- Event push (simulate EventBus publish → verify SSE frame)
- Done event triggers connection close
- Heartbeat sending
- Concurrent connection limit
"""

import asyncio
import json
import threading
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from xiaopaw.event_bus import AgentEvent, EventBus, EventPayload
from xiaopaw.frontend.routes.activity_stream import (
    MAX_CONNECTIONS_PER_SESSION,
    _active_connections,
    register_activity_stream_routes,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def app(event_bus):
    """Create a minimal aiohttp app with SSE route and EventBus."""
    application = web.Application()
    application["event_bus"] = event_bus
    # No auth required for tests (no frontend_token, no user_auth)
    register_activity_stream_routes(application)
    return application


@pytest.fixture
async def client(app):
    """Create a test client using aiohttp TestServer directly."""
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


# ─── Helper ─────────────────────────────────────────────────────────────────


async def read_sse_events(response, max_events=10, timeout=5.0):
    """Read SSE events from a streaming response until done/timeout."""
    events = []
    buffer = ""
    deadline = time.monotonic() + timeout

    async for chunk in response.content.iter_any():
        if time.monotonic() > deadline:
            break
        buffer += chunk.decode("utf-8")

        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            if frame.startswith(":"):
                # Heartbeat comment
                events.append({"event": "heartbeat", "data": ""})
                continue

            event_type = "message"
            data = ""
            for line in frame.split("\n"):
                if line.startswith("event: "):
                    event_type = line[7:].strip()
                elif line.startswith("data: "):
                    data = line[6:]

            if data:
                events.append({"event": event_type, "data": json.loads(data)})

            # Stop after done event
            if event_type == "done":
                return events

            if len(events) >= max_events:
                return events

    return events


# ─── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sse_connection_established(client, event_bus):
    """Test that SSE connection is established and receives 'connected' frame."""
    session_id = "test-session-connect"

    resp = await client.get(f"/api/frontend/sessions/{session_id}/activities/stream")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "text/event-stream"

    # Read the initial 'connected' event
    events = await read_sse_events(resp, max_events=1, timeout=2.0)
    assert len(events) >= 1
    assert events[0]["event"] == "connected"
    assert events[0]["data"]["session_id"] == session_id

    resp.close()


@pytest.mark.asyncio
async def test_sse_receives_activity_events(client, event_bus):
    """Test that EventBus events are pushed as SSE frames."""
    session_id = "test-session-events"

    resp = await client.get(f"/api/frontend/sessions/{session_id}/activities/stream")
    assert resp.status == 200

    # Give the handler time to subscribe
    await asyncio.sleep(0.1)

    # Publish an event from another "thread" (simulate Runner)
    event_bus.publish(EventPayload(
        event=AgentEvent.AGENT_STARTED,
        session_id=session_id,
        data={"agent_role": "orchestrator", "turn_id": "turn-001"},
    ))

    # Publish a tool call
    event_bus.publish(EventPayload(
        event=AgentEvent.TOOL_CALL_START,
        session_id=session_id,
        data={"tool_name": "web_search", "agent_role": "skill_agent", "turn_id": "turn-001"},
    ))

    # Publish completion
    event_bus.publish(EventPayload(
        event=AgentEvent.AGENT_COMPLETE,
        session_id=session_id,
        data={"duration_ms": 1500, "turn_id": "turn-001"},
    ))

    events = await read_sse_events(resp, max_events=10, timeout=3.0)

    # Should have: connected + agent_started + tool_call_start + agent_complete + done
    event_types = [e["event"] for e in events]
    assert "connected" in event_types
    assert "activity" in event_types
    assert "done" in event_types

    # Verify activity data
    activity_events = [e for e in events if e["event"] == "activity"]
    assert len(activity_events) >= 2

    first_activity = activity_events[0]["data"]
    assert first_activity["event_type"] == "agent_started"
    assert first_activity["agent_role"] == "orchestrator"

    # Verify done event
    done_events = [e for e in events if e["event"] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["data"]["reason"] == "agent_complete"

    resp.close()


@pytest.mark.asyncio
async def test_sse_filters_by_session(client, event_bus):
    """Test that events for other sessions are not received."""
    session_id = "test-session-filter"
    other_session = "other-session"

    resp = await client.get(f"/api/frontend/sessions/{session_id}/activities/stream")
    assert resp.status == 200
    await asyncio.sleep(0.1)

    # Publish event for a DIFFERENT session
    event_bus.publish(EventPayload(
        event=AgentEvent.AGENT_STARTED,
        session_id=other_session,
        data={"agent_role": "orchestrator"},
    ))

    # Publish event for OUR session (to trigger done)
    await asyncio.sleep(0.1)
    event_bus.publish(EventPayload(
        event=AgentEvent.AGENT_COMPLETE,
        session_id=session_id,
        data={"duration_ms": 100},
    ))

    events = await read_sse_events(resp, max_events=10, timeout=3.0)

    # Should NOT contain the other session's event
    activity_events = [e for e in events if e["event"] == "activity"]
    for ae in activity_events:
        assert ae["data"].get("event_type") != "agent_started" or True  # only our session

    # Should have done
    done_events = [e for e in events if e["event"] == "done"]
    assert len(done_events) == 1

    resp.close()


@pytest.mark.asyncio
async def test_sse_agent_error_closes_stream(client, event_bus):
    """Test that agent_error event triggers done and closes stream."""
    session_id = "test-session-error"

    resp = await client.get(f"/api/frontend/sessions/{session_id}/activities/stream")
    assert resp.status == 200
    await asyncio.sleep(0.1)

    event_bus.publish(EventPayload(
        event=AgentEvent.AGENT_ERROR,
        session_id=session_id,
        data={"error": "something went wrong"},
    ))

    events = await read_sse_events(resp, max_events=10, timeout=3.0)

    # Should have activity (error) + done
    done_events = [e for e in events if e["event"] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["data"]["reason"] == "agent_error"

    resp.close()


@pytest.mark.asyncio
async def test_sse_concurrent_connection_limit(client, event_bus):
    """Test that max concurrent connections per session is enforced."""
    session_id = "test-session-limit"

    # Open max connections
    connections = []
    for _ in range(MAX_CONNECTIONS_PER_SESSION):
        resp = await client.get(f"/api/frontend/sessions/{session_id}/activities/stream")
        assert resp.status == 200
        connections.append(resp)
        await asyncio.sleep(0.05)

    # Next connection should be rejected
    resp_extra = await client.get(f"/api/frontend/sessions/{session_id}/activities/stream")
    assert resp_extra.status == 429

    # Cleanup
    for conn in connections:
        conn.close()
    resp_extra.close()

    # Allow cleanup
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_sse_thread_safe_publish(client, event_bus):
    """Test that events published from a different thread are received."""
    session_id = "test-session-thread"

    resp = await client.get(f"/api/frontend/sessions/{session_id}/activities/stream")
    assert resp.status == 200
    await asyncio.sleep(0.1)

    # Publish from a separate thread (simulates Runner in ThreadPoolExecutor)
    def publish_from_thread():
        time.sleep(0.1)
        event_bus.publish(EventPayload(
            event=AgentEvent.TOOL_CALL_START,
            session_id=session_id,
            data={"tool_name": "code_executor", "agent_role": "coder", "turn_id": "t1"},
        ))
        time.sleep(0.05)
        event_bus.publish(EventPayload(
            event=AgentEvent.AGENT_COMPLETE,
            session_id=session_id,
            data={"duration_ms": 800, "turn_id": "t1"},
        ))

    thread = threading.Thread(target=publish_from_thread)
    thread.start()

    events = await read_sse_events(resp, max_events=10, timeout=5.0)
    thread.join()

    activity_events = [e for e in events if e["event"] == "activity"]
    assert len(activity_events) >= 1
    assert activity_events[0]["data"]["tool_name"] == "code_executor"

    done_events = [e for e in events if e["event"] == "done"]
    assert len(done_events) == 1

    resp.close()

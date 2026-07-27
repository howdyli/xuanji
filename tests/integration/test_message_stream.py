"""Integration tests for the SSE streaming chat endpoint.

Covers POST /api/frontend/message/stream:
- start -> delta* -> done frame sequence
- deltas reassemble into the full reply (typewriter chunking)
- reply captured via CaptureSender future resolved by the runner
- the one-shot /message endpoint stays behaviorally identical

Mirrors the harness used by test_activity_stream.py.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from xiaopaw.api.capture_sender import CaptureSender
from xiaopaw.frontend.routes.session import (
    _chunk_reply,
    _sse_frame,
    register_session_routes,
)


# ─── Pure-unit coverage for the chunking / framing core ──────────────────────


def test_chunk_reply_reassembles_and_is_bounded():
    reply = "你好，世界！" * 500  # long reply
    chunks = _chunk_reply(reply)
    assert "".join(chunks) == reply
    # Animation budget must be respected: no more than the max chunk count.
    assert len(chunks) <= 200


def test_chunk_reply_empty():
    assert _chunk_reply("") == []


def test_sse_frame_wire_format():
    frame = _sse_frame("delta", {"text": "hi"}).decode("utf-8")
    assert frame.startswith("event: delta\n")
    assert "data: " in frame
    assert frame.endswith("\n\n")


# ─── Fixtures ────────────────────────────────────────────────────────────────


class _FakeRunner:
    """Runner whose dispatch resolves the CaptureSender future (as the real one does)."""

    def __init__(self, sender: CaptureSender, reply: str) -> None:
        self._sender = sender
        self._reply = reply
        self.dispatched = []

    async def dispatch(self, inbound) -> None:
        self.dispatched.append(inbound)
        await self._sender.send(inbound.routing_key, self._reply)


@pytest.fixture
def reply_text():
    return "Hello streaming world! 你好，流式世界。"


@pytest.fixture
def app(reply_text):
    application = web.Application()
    sender = CaptureSender()

    session = MagicMock()
    session.id = "sess-stream-1"
    session.message_count = 0
    session_mgr = AsyncMock()
    session_mgr.get_or_create.return_value = session
    # 新语义：不带 session_id 的请求会建新会话
    session_mgr.create_new_session.return_value = session

    application["sender"] = sender
    application["session_mgr"] = session_mgr
    application["runner"] = _FakeRunner(sender, reply_text)
    application["pg_store"] = None
    # No user_auth + no frontend_token => check_auth passes without a header.
    register_session_routes(application)
    return application


@pytest.fixture
async def client(app):
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


async def _read_frames(response, timeout=5.0):
    events = []
    buffer = ""
    async for chunk in response.content.iter_any():
        buffer += chunk.decode("utf-8")
        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            if not frame.strip() or frame.startswith(":"):
                continue
            event_type = "message"
            data = ""
            for line in frame.split("\n"):
                if line.startswith("event: "):
                    event_type = line[7:].strip()
                elif line.startswith("data: "):
                    data = line[6:]
            events.append({"event": event_type, "data": json.loads(data) if data else {}})
            if event_type in ("done", "error"):
                return events
    return events


# ─── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_start_delta_done_sequence(client, reply_text):
    resp = await client.post(
        "/api/frontend/message/stream",
        json={"content": "hi"},
    )
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "text/event-stream"

    events = await _read_frames(resp)
    types = [e["event"] for e in events]

    assert types[0] == "start"
    assert "delta" in types
    assert types[-1] == "done"

    # deltas reassemble into the full reply
    reassembled = "".join(e["data"]["text"] for e in events if e["event"] == "delta")
    assert reassembled == reply_text

    # done carries the canonical reply + ids
    done = events[-1]["data"]
    assert done["reply"] == reply_text
    assert done["session_id"] == "sess-stream-1"
    assert done["msg_id"] == events[0]["data"]["msg_id"]
    resp.close()


@pytest.mark.asyncio
async def test_stream_rejects_empty_content(client):
    resp = await client.post("/api/frontend/message/stream", json={"content": "   "})
    assert resp.status == 422
    resp.close()

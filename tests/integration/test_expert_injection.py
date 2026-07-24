"""Integration tests for expert-context decoupling on POST /api/frontend/message.

Verifies that when a request carries ``expert``:
- the dispatched InboundMessage keeps ``content`` as the user's raw text and
  carries the system prompt out-of-band on ``expert_prompt``;
- persisted user message + session title stay free of the system prompt.

Mirrors the harness used by test_message_stream.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from xiaopaw.api.capture_sender import CaptureSender
from xiaopaw.frontend.routes.session import register_session_routes


REPLY = "好的，这是回复。"
RAW = "帮我写一个单元测试"
PROMPT = "你是资深测试专家，请用严谨的语气回答。"
DISPLAY = "测试专家团"


class _FakeRunner:
    """Runner that records the inbound and resolves the CaptureSender future."""

    def __init__(self, sender: CaptureSender) -> None:
        self._sender = sender
        self.dispatched: list = []

    async def dispatch(self, inbound) -> None:
        self.dispatched.append(inbound)
        await self._sender.send(inbound.routing_key, REPLY)


class _FakeExpertRegistry:
    def __init__(self, experts: dict) -> None:
        self._experts = experts

    def get(self, name: str):
        return self._experts.get(name)


@pytest.fixture
def pg_store():
    return AsyncMock()


@pytest.fixture
def runner_ref():
    return {}


@pytest.fixture
def app(pg_store, runner_ref):
    application = web.Application()
    sender = CaptureSender()

    session = MagicMock()
    session.id = "sess-expert-1"
    session.message_count = 0
    session_mgr = AsyncMock()
    session_mgr.get_or_create.return_value = session

    runner = _FakeRunner(sender)
    runner_ref["runner"] = runner

    application["sender"] = sender
    application["session_mgr"] = session_mgr
    application["runner"] = runner
    application["pg_store"] = pg_store
    application["expert_registry"] = _FakeExpertRegistry(
        {"tester": {"system_prompt": PROMPT, "display_name": DISPLAY}}
    )
    register_session_routes(application)
    return application


@pytest.fixture
async def client(app):
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


@pytest.mark.asyncio
async def test_expert_prompt_is_decoupled_from_content(client, runner_ref, pg_store):
    resp = await client.post(
        "/api/frontend/message",
        json={"content": RAW, "expert": "tester"},
    )
    assert resp.status == 200

    inbound = runner_ref["runner"].dispatched[0]
    # content stays the user's raw text; prompt travels out-of-band
    assert inbound.content == RAW
    assert inbound.expert_prompt == PROMPT
    assert inbound.expert_name == DISPLAY

    # Persisted user message keeps the raw text (no system prompt leakage)
    user_calls = [c for c in pg_store.save_conversation.await_args_list if c.args[3] == "user"]
    assert user_calls, "expected a user-role save_conversation call"
    assert user_calls[0].args[4] == RAW
    assert PROMPT not in user_calls[0].args[4]

    # Session title derives from the raw content only
    assert pg_store.save_session.await_args.kwargs["title"] == RAW[:80]
    resp.close()


@pytest.mark.asyncio
async def test_no_expert_leaves_prompt_empty(client, runner_ref):
    resp = await client.post("/api/frontend/message", json={"content": "你好"})
    assert resp.status == 200

    inbound = runner_ref["runner"].dispatched[0]
    assert inbound.content == "你好"
    assert inbound.expert_prompt == ""
    assert inbound.expert_name == ""
    resp.close()


@pytest.mark.asyncio
async def test_unknown_expert_is_ignored(client, runner_ref):
    resp = await client.post(
        "/api/frontend/message",
        json={"content": "你好", "expert": "ghost"},
    )
    assert resp.status == 200

    inbound = runner_ref["runner"].dispatched[0]
    assert inbound.content == "你好"
    assert inbound.expert_prompt == ""
    resp.close()

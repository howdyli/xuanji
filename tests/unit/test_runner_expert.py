"""Unit tests for expert-context handling in Runner._handle.

Verifies the decoupling: the expert system prompt is prepended ONLY to the
agent input, while everything else (persistence, hooks) keeps the user's raw
content.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xiaopaw.models import InboundMessage
from xiaopaw.runner import Runner


def _make_runner(agent_fn):
    session = MagicMock()
    session.id = "sess-expert-1"
    session.verbose = False
    session_mgr = AsyncMock()
    session_mgr.get_or_create.return_value = session
    session_mgr.load_history.return_value = []
    sender = AsyncMock()
    sender.send_thinking.return_value = None
    runner = Runner(session_mgr=session_mgr, sender=sender, agent_fn=agent_fn)
    return runner, session_mgr


@pytest.mark.asyncio
async def test_handle_prepends_expert_prompt_only_to_agent_input():
    captured: dict[str, str] = {}

    async def agent_fn(content, history, session_id, key, verbose):
        captured["content"] = content
        return "回复", []

    runner, session_mgr = _make_runner(agent_fn)
    inbound = InboundMessage(
        routing_key="p2p:web_test",
        content="帮我写单元测试",
        msg_id="m1",
        expert_prompt="你是资深测试专家。",
        expert_name="测试专家",
    )

    await runner._handle(inbound)

    # Agent sees the synthesized effective input (prompt + raw text).
    assert captured["content"] == "你是资深测试专家。\n\n---\n\n帮我写单元测试"
    # Persistence keeps the user's raw content (no system prompt leakage).
    session_mgr.append.assert_awaited_once()
    assert session_mgr.append.await_args.kwargs["user"] == "帮我写单元测试"


@pytest.mark.asyncio
async def test_handle_without_expert_passes_raw_content():
    captured: dict[str, str] = {}

    async def agent_fn(content, history, session_id, key, verbose):
        captured["content"] = content
        return "ok", []

    runner, _ = _make_runner(agent_fn)
    inbound = InboundMessage(
        routing_key="p2p:web_test",
        content="你好",
        msg_id="m2",
    )

    await runner._handle(inbound)

    # No expert => agent receives the raw content unchanged.
    assert captured["content"] == "你好"

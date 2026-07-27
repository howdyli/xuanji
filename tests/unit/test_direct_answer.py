"""Unit tests for the direct-answer bypass (短期#7).

Covers the conservative intent classifier and the Runner-level routing:
simple chat -> direct_fn; task-like content / skill hints / bypass failure
-> full crew orchestration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from xiaopaw.agents.direct_answer import is_simple_chat
from xiaopaw.models import InboundMessage
from xiaopaw.runner import Runner


# ── classifier ───────────────────────────────────────────────────


@pytest.mark.parametrize("content", [
    "你好",
    "什么是量子纠缠？",
    "解释一下依赖注入的概念",
    "太阳系有几颗行星",
    "谢谢，明白了",
])
def test_simple_chat_accepted(content):
    assert is_simple_chat(content) is True


@pytest.mark.parametrize("content", [
    "",
    "   ",
    "/new",
    "/status",
    "帮我生成一份周报 PPT",
    "把这个导出为 pdf",
    "搜索一下最新的 AI 新闻",
    "https://example.com 这个网页讲了什么",
    "记住我喜欢简洁的回复",
    "每天早上9点提醒我开会",
    "运行这个脚本看看输出",
    "写一份市场分析报告",
    "x" * 301,  # 超长 → 大概率是任务描述
])
def test_task_like_content_rejected(content):
    assert is_simple_chat(content) is False


# ── runner bypass routing ────────────────────────────────────────


def _make_runner(agent_fn, direct_fn):
    session = MagicMock()
    session.id = "sess-direct-1"
    session.verbose = False
    session_mgr = AsyncMock()
    session_mgr.get_or_create.return_value = session
    session_mgr.load_history.return_value = []
    sender = AsyncMock()
    sender.send_thinking.return_value = None
    return Runner(
        session_mgr=session_mgr, sender=sender,
        agent_fn=agent_fn, direct_fn=direct_fn,
    )


@pytest.mark.asyncio
async def test_simple_chat_routes_to_direct_fn():
    calls: list[str] = []

    async def agent_fn(content, history, session_id, key, verbose):
        calls.append("crew")
        return "crew 回复", []

    async def direct_fn(content, history, session_id, key, verbose):
        calls.append("direct")
        return "直答回复", []

    runner = _make_runner(agent_fn, direct_fn)
    await runner._handle(InboundMessage(
        routing_key="p2p:web_test", content="你好", msg_id="d1",
    ))

    assert calls == ["direct"]
    runner._sender.send.assert_awaited_once_with("p2p:web_test", "直答回复")


@pytest.mark.asyncio
async def test_task_content_routes_to_crew():
    calls: list[str] = []

    async def agent_fn(content, history, session_id, key, verbose):
        calls.append("crew")
        return "crew 回复", []

    async def direct_fn(content, history, session_id, key, verbose):
        calls.append("direct")
        return "直答回复", []

    runner = _make_runner(agent_fn, direct_fn)
    await runner._handle(InboundMessage(
        routing_key="p2p:web_test", content="帮我生成一份周报 PPT", msg_id="d2",
    ))

    assert calls == ["crew"]


@pytest.mark.asyncio
async def test_skill_hints_disable_bypass():
    calls: list[str] = []

    async def agent_fn(content, history, session_id, key, verbose):
        calls.append("crew")
        return "ok", []

    async def direct_fn(content, history, session_id, key, verbose):
        calls.append("direct")
        return "ok", []

    runner = _make_runner(agent_fn, direct_fn)
    await runner._handle(InboundMessage(
        routing_key="p2p:web_test", content="你好",
        msg_id="d3", skill_hints=["memory-save"],
    ))

    assert calls == ["crew"]


@pytest.mark.asyncio
async def test_bypass_failure_falls_back_to_crew():
    calls: list[str] = []

    async def agent_fn(content, history, session_id, key, verbose):
        calls.append("crew")
        return "crew 兜底回复", []

    async def direct_fn(content, history, session_id, key, verbose):
        calls.append("direct")
        raise RuntimeError("LLM unavailable")

    runner = _make_runner(agent_fn, direct_fn)
    await runner._handle(InboundMessage(
        routing_key="p2p:web_test", content="你好", msg_id="d4",
    ))

    assert calls == ["direct", "crew"]
    runner._sender.send.assert_awaited_once_with("p2p:web_test", "crew 兜底回复")


@pytest.mark.asyncio
async def test_empty_direct_reply_falls_back_to_crew():
    async def agent_fn(content, history, session_id, key, verbose):
        return "crew 兜底回复", []

    async def direct_fn(content, history, session_id, key, verbose):
        return "", []

    runner = _make_runner(agent_fn, direct_fn)
    await runner._handle(InboundMessage(
        routing_key="p2p:web_test", content="你好", msg_id="d5",
    ))

    runner._sender.send.assert_awaited_once_with("p2p:web_test", "crew 兜底回复")


@pytest.mark.asyncio
async def test_no_direct_fn_keeps_legacy_path():
    calls: list[str] = []

    async def agent_fn(content, history, session_id, key, verbose):
        calls.append("crew")
        return "ok", []

    runner = _make_runner(agent_fn, direct_fn=None)
    await runner._handle(InboundMessage(
        routing_key="p2p:web_test", content="你好", msg_id="d6",
    ))

    assert calls == ["crew"]

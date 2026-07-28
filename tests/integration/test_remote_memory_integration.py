"""Integration tests: RemoteMemoryStore ↔ 真实 agent-memory-system 后端.

前置条件（否则整个模块跳过）：
- 记忆服务已启动: cd ../pm/agent-memory-system && docker-compose up -d
- 已安装 SDK:     pip install -e ../pm/agent-memory-system/sdk-python
- 环境变量:        AGENT_MEMORY_URL（含 /api/v1）+ AGENT_MEMORY_API_KEY
"""

from __future__ import annotations

import os
import time
import uuid
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.integration

_BASE_URL = os.environ.get("AGENT_MEMORY_URL", "")
_API_KEY = os.environ.get("AGENT_MEMORY_API_KEY", "")

if not _BASE_URL or not _API_KEY:
    pytest.skip(
        "AGENT_MEMORY_URL / AGENT_MEMORY_API_KEY not set", allow_module_level=True
    )
pytest.importorskip("agent_memory")

from xiaopaw.memory.remote_memory import RemoteMemoryStore  # noqa: E402


@pytest.fixture
async def store():
    s = RemoteMemoryStore()
    s.init_from_config(
        SimpleNamespace(
            remote_base_url=_BASE_URL,
            remote_api_key=_API_KEY,
            remote_timeout=15.0,
            recall_top_k=5,
            recall_max_chars=4000,
            max_save_length=2000,
        ),
        SimpleNamespace(enable_remote_memory=True),
    )
    assert s.is_enabled
    yield s
    await s.close()


async def test_save_then_recall_roundtrip(store):
    """remember→recall 闭环：写入的片段应能被语义召回。"""
    marker = f"xiaopaw-integration-{uuid.uuid4().hex[:8]}"
    await store.save_turn(
        session_id=f"it-{marker}",
        routing_key="p2p:web_it_user",
        user_message=f"请记住这个集成测试标记 {marker}",
        assistant_reply=f"好的，已记住标记 {marker}",
    )
    # 后端向量索引可能异步，轮询召回
    context = ""
    for _ in range(5):
        context = await store.recall(f"集成测试标记 {marker}")
        if marker in context:
            break
        time.sleep(1)
    assert marker in context, f"recall 未命中写入片段, got: {context[:200]!r}"


async def test_recall_never_raises_on_bad_endpoint():
    """错误地址下 recall 降级为空串（/api/v1 前缀缺失等配置错误不炸主流程）。"""
    s = RemoteMemoryStore()
    s.init_from_config(
        SimpleNamespace(
            remote_base_url="http://127.0.0.1:1/api/v1",  # 不可达端口
            remote_api_key="amk_invalid",
            remote_timeout=2.0,
            recall_top_k=5,
            recall_max_chars=4000,
            max_save_length=2000,
        ),
        SimpleNamespace(enable_remote_memory=True),
    )
    assert await s.recall("任意查询") == ""
    await s.save_turn("s", "rk", "u", "a")  # 同样不应抛
    await s.close()

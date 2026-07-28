"""Unit tests for xiaopaw.memory.remote_memory (agent-memory-system SDK 对接)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from xiaopaw.memory.remote_memory import RemoteMemoryStore


def _memory_cfg(**overrides) -> SimpleNamespace:
    base = dict(
        remote_base_url="http://localhost:8000/api/v1",
        remote_api_key="amk_test",
        remote_timeout=5.0,
        recall_top_k=5,
        recall_max_chars=4000,
        max_save_length=2000,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _flags(enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(enable_remote_memory=enabled)


def _enabled_store(**cfg_overrides) -> RemoteMemoryStore:
    store = RemoteMemoryStore()
    store.init_from_config(_memory_cfg(**cfg_overrides), _flags(True))
    return store


class TestInitFromConfig:
    def test_flag_off_stays_disabled(self):
        store = RemoteMemoryStore()
        store.init_from_config(_memory_cfg(), _flags(False))
        assert not store.is_enabled

    def test_missing_base_url_stays_disabled(self):
        store = RemoteMemoryStore()
        store.init_from_config(_memory_cfg(remote_base_url=""), _flags(True))
        assert not store.is_enabled

    def test_missing_api_key_stays_disabled(self):
        store = RemoteMemoryStore()
        store.init_from_config(_memory_cfg(remote_api_key=""), _flags(True))
        assert not store.is_enabled

    def test_full_config_enables(self):
        store = _enabled_store()
        assert store.is_enabled


class TestRecall:
    async def test_disabled_returns_empty(self):
        store = RemoteMemoryStore()
        assert await store.recall("query") == ""

    async def test_empty_query_returns_empty(self):
        store = _enabled_store()
        store._client = AsyncMock()
        assert await store.recall("   ") == ""
        store._client.recall_context.assert_not_called()

    async def test_success_returns_context(self):
        store = _enabled_store()
        client = AsyncMock()
        client.recall_context.return_value = "记住：用户偏好中文回复"
        store._client = client
        result = await store.recall("用户偏好", routing_key="p2p:web_alice")
        assert result == "记住：用户偏好中文回复"
        client.recall_context.assert_awaited_once_with("用户偏好", top_k=5)

    async def test_result_truncated_to_max_chars(self):
        store = _enabled_store(recall_max_chars=200)
        client = AsyncMock()
        client.recall_context.return_value = "x" * 1000
        store._client = client
        result = await store.recall("q")
        assert len(result) == 200
        assert result.endswith("...(截断)")

    async def test_http_error_degrades_to_empty(self):
        store = _enabled_store()
        client = AsyncMock()
        client.recall_context.side_effect = RuntimeError("boom")
        store._client = client
        assert await store.recall("q") == ""

    async def test_timeout_degrades_to_empty(self):
        store = _enabled_store(remote_timeout=1.0)

        async def _hang(*args, **kwargs):
            await asyncio.sleep(10)

        client = AsyncMock()
        client.recall_context.side_effect = _hang
        store._client = client
        store._timeout = 0.01
        assert await store.recall("q") == ""


class TestSaveTurn:
    async def test_disabled_is_noop(self):
        store = RemoteMemoryStore()
        # 不应抛异常，也不应尝试创建客户端
        await store.save_turn("s1", "rk", "hi", "hello")
        assert store._client is None

    async def test_success_sends_fragment_with_metadata(self):
        store = _enabled_store()
        client = AsyncMock()
        store._client = client
        await store.save_turn("s1", "p2p:web_alice", "问题", "回答")
        client.remember_fragment.assert_awaited_once()
        kwargs = client.remember_fragment.await_args.kwargs
        assert kwargs["fragment_type"] == "info"
        assert "问题" in kwargs["content"] and "回答" in kwargs["content"]
        meta = kwargs["metadata"]
        assert meta["session_id"] == "s1"
        assert meta["routing_key"] == "p2p:web_alice"
        assert meta["source"] == "xiaopaw"

    async def test_summary_preferred_over_raw_dialog(self):
        store = _enabled_store()
        client = AsyncMock()
        store._client = client
        await store.save_turn("s1", "rk", "u", "a", summary="一句话摘要")
        assert client.remember_fragment.await_args.kwargs["content"] == "一句话摘要"

    async def test_content_truncated_to_max_save_length(self):
        store = _enabled_store(max_save_length=50)
        client = AsyncMock()
        store._client = client
        await store.save_turn("s1", "rk", "u", "a", summary="y" * 500)
        assert len(client.remember_fragment.await_args.kwargs["content"]) == 50

    async def test_write_error_swallowed(self):
        store = _enabled_store()
        client = AsyncMock()
        client.remember_fragment.side_effect = RuntimeError("boom")
        store._client = client
        # 不应向上抛
        await store.save_turn("s1", "rk", "u", "a")


class TestSaveTurnBackground:
    async def test_disabled_schedules_nothing(self):
        store = RemoteMemoryStore()
        store.save_turn_background("s1", "rk", "u", "a")
        assert not store._pending_tasks

    async def test_enabled_schedules_and_completes(self):
        store = _enabled_store()
        client = AsyncMock()
        store._client = client
        store.save_turn_background("s1", "rk", "u", "a")
        assert len(store._pending_tasks) == 1
        await asyncio.gather(*store._pending_tasks)
        client.remember_fragment.assert_awaited_once()
        assert not store._pending_tasks  # done callback 清理引用


class TestSdkNotInstalled:
    async def test_missing_sdk_degrades_to_disabled(self, monkeypatch):
        import builtins

        store = _enabled_store()
        real_import = builtins.__import__

        def _no_sdk(name, *args, **kwargs):
            if name.startswith("agent_memory"):
                raise ImportError("No module named 'agent_memory'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_sdk)
        assert await store.recall("q") == ""
        assert not store.is_enabled


class TestClose:
    async def test_close_releases_client(self):
        store = _enabled_store()
        client = AsyncMock()
        store._client = client
        await store.close()
        client.close.assert_awaited_once()
        assert store._client is None


# ===================================================================
# Phase 4
# ===================================================================


class TestStats:
    """FR-6 可观测性：四项计数 + stats() + 汇总日志。"""

    async def test_recall_counters(self):
        store = _enabled_store()
        client = AsyncMock()
        client.recall_context.return_value = "命中内容"
        store._client = client
        await store.recall("q")
        client.recall_context.return_value = ""
        await store.recall("q")  # 空结果：total+1，hit 不加
        s = store.stats()
        assert s["recall_total"] == 2 and s["recall_hit"] == 1

    async def test_save_counters(self):
        store = _enabled_store()
        client = AsyncMock()
        store._client = client
        await store.save_turn("s1", "rk", "u", "a", summary="ok")
        client.remember_fragment.side_effect = RuntimeError("boom")
        await store.save_turn("s1", "rk", "u", "a", summary="ok")
        s = store.stats()
        assert s["save_total"] == 2 and s["save_failed"] == 1

    async def test_stats_includes_pending_tasks(self):
        store = _enabled_store()
        assert store.stats()["pending_tasks"] == 0

    async def test_summary_log_every_100_ops(self, caplog):
        import logging

        store = _enabled_store()
        client = AsyncMock()
        client.recall_context.return_value = "x"
        store._client = client
        with caplog.at_level(logging.INFO, logger="xiaopaw.memory.remote_memory"):
            for _ in range(100):
                await store.recall("q")
        assert any("remote memory stats" in r.message for r in caplog.records)


class TestLifecycleGovernance:
    """FR-3 片段生命周期：TTL + 启发式 importance 打分。"""

    async def test_default_ttl_90_days(self):
        store = _enabled_store()
        client = AsyncMock()
        store._client = client
        await store.save_turn("s1", "rk", "今天天气不错", "a", summary="ok")
        assert client.remember_fragment.await_args.kwargs["ttl"] == 90 * 86400

    async def test_ttl_zero_means_permanent(self):
        store = _enabled_store(fragment_ttl_days=0)
        client = AsyncMock()
        store._client = client
        await store.save_turn("s1", "rk", "u", "a", summary="ok")
        assert client.remember_fragment.await_args.kwargs["ttl"] is None

    async def test_explicit_statement_scores_high(self):
        store = _enabled_store()
        client = AsyncMock()
        store._client = client
        await store.save_turn("s1", "rk", "记住我是工程师", "a", summary="ok")
        assert client.remember_fragment.await_args.kwargs["importance_score"] == 0.7

    async def test_casual_chat_scores_default(self):
        store = _enabled_store()
        client = AsyncMock()
        store._client = client
        await store.save_turn("s1", "rk", "今天天气不错", "a", summary="ok")
        assert client.remember_fragment.await_args.kwargs["importance_score"] == 0.4

    async def test_importance_configurable(self):
        store = _enabled_store(importance_high=0.9, importance_default=0.2)
        assert store._score_importance("记住这个") == 0.9
        assert store._score_importance("随便聊聊") == 0.2


class TestSummarization:
    """FR-4 摘要化写入：失败/超时回退原文拼接，不丢写入。"""

    async def test_no_models_returns_empty(self):
        store = _enabled_store()
        # 测试环境 model_router 未初始化 → 直接返回空串（不调 LLM）
        assert await store._summarize_turn("u", "a") == ""

    async def test_summary_used_as_content(self, monkeypatch):
        store = _enabled_store()
        client = AsyncMock()
        store._client = client

        async def _fake_summary(u, a):
            return "一句话 LLM 摘要"

        monkeypatch.setattr(store, "_summarize_turn", _fake_summary)
        await store.save_turn("s1", "rk", "问题", "回答")
        assert client.remember_fragment.await_args.kwargs["content"] == "一句话 LLM 摘要"

    async def test_summarize_failure_falls_back_to_raw(self, monkeypatch):
        store = _enabled_store()
        client = AsyncMock()
        store._client = client

        async def _fail_summary(u, a):
            return ""  # 摘要失败/超时内部已处理为空串

        monkeypatch.setattr(store, "_summarize_turn", _fail_summary)
        await store.save_turn("s1", "rk", "问题", "回答")
        content = client.remember_fragment.await_args.kwargs["content"]
        assert "问题" in content and "回答" in content  # 原文拼接回退

    async def test_caller_summary_skips_llm(self, monkeypatch):
        store = _enabled_store()
        client = AsyncMock()
        store._client = client
        called = False

        async def _spy(u, a):
            nonlocal called
            called = True
            return ""

        monkeypatch.setattr(store, "_summarize_turn", _spy)
        await store.save_turn("s1", "rk", "u", "a", summary="调用方摘要")
        assert not called  # 调用方已提供摘要，不再调 LLM


class TestPreferences:
    """FR-1 用户偏好（Variables upsert）。"""

    async def test_set_preference_calls_remember(self):
        store = _enabled_store()
        client = AsyncMock()
        client.remember.return_value = True
        store._client = client
        assert await store.set_preference("reply_language", "英文")
        client.remember.assert_awaited_once_with("reply_language", "英文")

    async def test_set_preference_disabled_returns_false(self):
        store = RemoteMemoryStore()
        assert not await store.set_preference("k", "v")

    async def test_set_preference_error_swallowed(self):
        store = _enabled_store()
        client = AsyncMock()
        client.remember.side_effect = RuntimeError("boom")
        store._client = client
        assert not await store.set_preference("k", "v")

    async def test_get_preferences_returns_dict(self):
        store = _enabled_store()
        client = AsyncMock()
        client.list_variables.return_value = {"reply_language": "英文"}
        store._client = client
        assert await store.get_preferences() == {"reply_language": "英文"}

    async def test_get_preferences_capped_at_20(self):
        store = _enabled_store()
        client = AsyncMock()
        client.list_variables.return_value = {f"k{i}": i for i in range(30)}
        store._client = client
        prefs = await store.get_preferences()
        assert len(prefs) == 20
        assert "k29" in prefs and "k9" not in prefs  # 保留最新尾部

    async def test_get_preferences_error_returns_empty(self):
        store = _enabled_store()
        client = AsyncMock()
        client.list_variables.side_effect = RuntimeError("boom")
        store._client = client
        assert await store.get_preferences() == {}

    def test_set_preference_sync_disabled_returns_false(self):
        store = RemoteMemoryStore()
        assert not store.set_preference_sync("k", "v")

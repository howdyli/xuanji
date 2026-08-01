"""Unit tests for xiaopaw.memory.remote_memory (agent-memory-system SDK 对接)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import xiaopaw.memory.remote_memory as rm_module
from xiaopaw.memory.remote_memory import RemoteMemoryStore

_LOGGER_NAME = "xiaopaw.memory.remote_memory"


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
        # P3 差异化 TTL：info 永久；白名单外类型回退默认 90 天
        await store.save_turn("s1", "rk", "今天天气不错", "a", summary="ok")
        assert client.remember_fragment.await_args.kwargs["ttl"] is None
        await store.save_turn("s1", "rk", "u", "a", summary="ok", fragment_type="other")
        assert client.remember_fragment.await_args.kwargs["ttl"] == 90 * 86400

    async def test_ttl_zero_means_permanent(self):
        store = _enabled_store(fragment_ttl_days=0)
        client = AsyncMock()
        store._client = client
        await store.save_turn("s1", "rk", "u", "a", summary="ok", fragment_type="other")
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


# ===================================================================
# 玄机侧记忆对接第一阶段：启动自检 / 分级错误 / 降级信号 / 调度下线
# ===================================================================


def _http_status_error(status_code: int, json_data: dict | None = None):
    """构造带指定状态码响应的 httpx.HTTPStatusError。"""
    import httpx

    resp = _FakeResponse(status_code, json_data)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}", request=httpx.Request("GET", "http://t"), response=resp
    )


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: dict | None = None):
        self.status_code = status_code
        self._json = json_data
        self.text = str(json_data or "")

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _http_status_error(self.status_code, self._json)


class _FakeAsyncClient:
    """替身 httpx.AsyncClient：按 URL 后缀返回预置响应/异常。"""

    routes: dict[str, object] = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def _dispatch(self, url: str):
        for suffix, result in type(self).routes.items():
            if url.endswith(suffix):
                if isinstance(result, Exception):
                    raise result
                return result
        return _FakeResponse(404, {"code": "NOT_FOUND", "message": "no route"})

    async def get(self, url, **kwargs):
        return await self._dispatch(url)

    async def post(self, url, **kwargs):
        return await self._dispatch(url)

    async def request(self, method=None, url=None, **kwargs):
        # SDK _AsyncHttpTransport 统一走 client.request(method=..., url=...)
        return await self._dispatch(url)


def _patch_httpx(monkeypatch, routes: dict) -> None:
    import httpx

    _FakeAsyncClient.routes = routes
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)


class TestApiKeyFormatCheck:
    """改造 1a：启动时校验 remote_api_key 格式（amk_ 前缀）。"""

    def test_bad_prefix_logs_error_but_stays_enabled(self, caplog):
        store = RemoteMemoryStore()
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            store.init_from_config(_memory_cfg(remote_api_key="sk-wrong"), _flags(True))
        assert store.is_enabled  # 只诊断不禁用
        assert any(
            "amk_" in r.message and r.levelno == logging.ERROR for r in caplog.records
        )

    def test_good_prefix_no_error(self, caplog):
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            _enabled_store()
        assert not [r for r in caplog.records if r.levelno == logging.ERROR]


class TestStartupConnectivityCheck:
    """改造 1b：一次性轻量连通性自检，区分三类诊断，绝不抛异常。"""

    async def test_backend_unreachable_logs_error(self, monkeypatch, caplog):
        import httpx

        store = _enabled_store()
        _patch_httpx(monkeypatch, {"/health/live": httpx.ConnectError("refused")})
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            await store._startup_connectivity_check()
        assert any("unreachable" in r.message for r in caplog.records)

    async def test_invalid_key_logs_error_with_ams_code(self, monkeypatch, caplog):
        store = _enabled_store()
        _patch_httpx(monkeypatch, {
            "/health/live": _FakeResponse(200, {"status": "alive"}),
            "/system/llm/resilience": _FakeResponse(401, {
                "code": "AUTH_INVALID_CREDENTIALS",
                "message": "Invalid or revoked API key",
            }),
        })
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            await store._startup_connectivity_check()
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert any("API key rejected" in m and "AUTH_INVALID_CREDENTIALS" in m for m in errors)

    async def test_healthy_backend_logs_ok(self, monkeypatch, caplog):
        store = _enabled_store()
        _patch_httpx(monkeypatch, {
            "/health/live": _FakeResponse(200, {"status": "alive"}),
            "/system/llm/resilience": _FakeResponse(200, {"success": True}),
        })
        with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
            await store._startup_connectivity_check()
        assert any("startup check OK" in r.message for r in caplog.records)

    async def test_check_never_raises(self, monkeypatch):
        store = _enabled_store()
        _patch_httpx(monkeypatch, {"/health/live": RuntimeError("boom")})
        await store._startup_connectivity_check()  # 不抛即通过

    def test_schedule_noop_when_disabled(self):
        store = RemoteMemoryStore()
        store.schedule_startup_check()
        assert not store._pending_tasks


class TestErrorClassification:
    """改造 2：分级错误处理（4xx 不重试 ERROR，5xx 退避重试 WARNING）。"""

    def test_classify_timeout_and_connect_retryable(self):
        import httpx

        assert rm_module._classify_error(asyncio.TimeoutError()) == ("timeout", True)
        assert rm_module._classify_error(httpx.ConnectError("x")) == ("connect", True)
        assert rm_module._classify_error(_http_status_error(500)) == ("http_5xx", True)
        assert rm_module._classify_error(_http_status_error(401)) == ("http_4xx", False)
        assert rm_module._classify_error(RuntimeError("x")) == ("unknown", False)

    def test_classify_sdk_exceptions(self):
        """G7：SDK 类型化异常按 status_code 分级，不归为 unknown。"""
        from agent_memory import exceptions as sdk_exc

        assert rm_module._classify_error(sdk_exc.HTTPError(500, "boom")) == ("http_5xx", True)
        assert rm_module._classify_error(sdk_exc.HTTPError(400, "bad")) == ("http_4xx", False)
        assert rm_module._classify_error(sdk_exc.AuthenticationError("bad key")) == ("http_4xx", False)
        assert rm_module._classify_error(sdk_exc.NotFoundError("missing")) == ("http_4xx", False)
        assert rm_module._classify_error(sdk_exc.TransportError("conn refused")) == ("connect", True)

    async def test_recall_401_logs_error_and_no_retry(self, caplog):
        store = _enabled_store()
        client = AsyncMock()
        client.recall_context.side_effect = _http_status_error(401, {
            "code": "AUTH_INVALID_CREDENTIALS", "message": "Invalid or revoked API key",
        })
        store._client = client
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert await store.recall("q") == ""
        assert client.recall_context.call_count == 1  # 4xx 不重试
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert any("AUTH_INVALID_CREDENTIALS" in m and "401" in m for m in errors)

    async def test_recall_5xx_retries_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(rm_module, "_RETRY_BACKOFFS", (0.01, 0.02))
        store = _enabled_store()
        client = AsyncMock()
        client.recall_context.side_effect = [_http_status_error(500), "召回成功"]
        store._client = client
        assert await store.recall("q") == "召回成功"
        assert client.recall_context.call_count == 2

    async def test_recall_5xx_exhausts_retries_returns_empty(self, monkeypatch, caplog):
        monkeypatch.setattr(rm_module, "_RETRY_BACKOFFS", (0.01, 0.02))
        store = _enabled_store()
        client = AsyncMock()
        client.recall_context.side_effect = _http_status_error(503, {
            "code": "INTERNAL_ERROR", "message": "upstream down",
        })
        store._client = client
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert await store.recall("q") == ""
        assert client.recall_context.call_count == 3  # 1 次 + 2 次重试
        # 5xx 最终失败是 WARNING 而非 ERROR
        assert not [r for r in caplog.records if r.levelno == logging.ERROR]

    async def test_connect_error_logs_unreachable_warning(self, monkeypatch, caplog):
        import httpx

        monkeypatch.setattr(rm_module, "_RETRY_BACKOFFS", (0.01,))
        store = _enabled_store()
        client = AsyncMock()
        client.recall_context.side_effect = httpx.ConnectError("refused")
        store._client = client
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert await store.recall("q") == ""
        assert any("unreachable or timed out" in r.getMessage() for r in caplog.records)

    async def test_retry_respects_timeout_budget(self, monkeypatch):
        """重试总耗时不突破 remote_timeout 预算：预算耗尽后不再重试。"""
        store = _enabled_store()
        store._timeout = 0.05  # 退避 0.5s 远大于预算 → 首次失败后直接放弃
        client = AsyncMock()
        client.recall_context.side_effect = _http_status_error(500)
        store._client = client
        assert await store.recall("q") == ""
        assert client.recall_context.call_count == 1


class TestDegradedSignal:
    """改造 3：识别 degraded / circuit_open 降级信号并区分记录。"""

    async def test_recall_layered_degraded_logs_reason(self, monkeypatch, caplog):
        store = _enabled_store()
        _patch_httpx(monkeypatch, {
            "/memory/recall/auto": _FakeResponse(200, {
                "profile": "p", "semantic": "", "entity_expansion": "",
                "total_tokens": 1, "degraded": True,
            }),
        })
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            result = await store.recall_layered("q")
        assert result["profile"] == "p"  # 降级信号不影响正常返回
        assert any("degrade_reason=degraded" in r.getMessage() for r in caplog.records)

    async def test_recall_layered_circuit_open_logs_reason(self, monkeypatch, caplog):
        store = _enabled_store()
        _patch_httpx(monkeypatch, {
            "/memory/recall/auto": _FakeResponse(200, {
                "profile": "", "semantic": "", "entity_expansion": "",
                "total_tokens": 0, "degraded": True, "circuit_open": True,
            }),
        })
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            await store.recall_layered("q")
        # circuit_open 优先于 degraded
        assert any("degrade_reason=circuit_open" in r.getMessage() for r in caplog.records)

    async def test_normal_response_no_degrade_log(self, monkeypatch, caplog):
        store = _enabled_store()
        _patch_httpx(monkeypatch, {
            "/memory/recall/auto": _FakeResponse(200, {
                "profile": "p", "semantic": "s", "entity_expansion": "",
                "total_tokens": 2,
            }),
        })
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            await store.recall_layered("q")
        assert not any("degrade_reason" in r.getMessage() for r in caplog.records)


class TestResponseFieldDefense:
    """改造 2 附带：响应字段缺失时返回明确失败值，避免 NoneType 错误。"""

    def _table_store(self) -> RemoteMemoryStore:
        store = _enabled_store()
        store._structured_tables = {"todo": [{"name": "title", "type": "text"}]}
        store._ensured_tables.add("todo")
        return store

    def test_add_record_missing_id_returns_none(self, monkeypatch, caplog):
        store = self._table_store()
        monkeypatch.setattr(
            store, "_table_request_sync",
            lambda *a, **k: _FakeResponse(200, {"success": True}),
        )
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert store.add_record_sync("todo", {"title": "x"}) is None
        assert any("missing record_id" in r.message for r in caplog.records)

    def test_add_record_id_fallback_to_id_field(self, monkeypatch):
        store = self._table_store()
        monkeypatch.setattr(
            store, "_table_request_sync", lambda *a, **k: _FakeResponse(200, {"id": 7}),
        )
        assert store.add_record_sync("todo", {"title": "x"}) == 7

    def test_query_records_missing_records_returns_none(self, monkeypatch, caplog):
        store = self._table_store()
        monkeypatch.setattr(
            store, "_table_request_sync",
            lambda *a, **k: _FakeResponse(200, {"success": True}),
        )
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert store.query_records_sync("todo") is None
        assert any("missing 'records'" in r.message for r in caplog.records)

    def test_add_record_non_dict_json_returns_none(self, monkeypatch, caplog):
        """评审修复：非 dict JSON（如 list）不得抛 AttributeError 逃逸到工具线程。"""
        store = self._table_store()
        monkeypatch.setattr(
            store, "_table_request_sync",
            lambda *a, **k: _FakeResponse(200, [1, 2, 3]),
        )
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert store.add_record_sync("todo", {"title": "x"}) is None
        assert any("non-dict response body" in r.message for r in caplog.records)

    def test_query_records_non_dict_json_returns_none(self, monkeypatch, caplog):
        store = self._table_store()
        monkeypatch.setattr(
            store, "_table_request_sync",
            lambda *a, **k: _FakeResponse(200, ["r1", "r2"]),
        )
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert store.query_records_sync("todo") is None
        assert any("non-dict response body" in r.message for r in caplog.records)

    async def test_extract_and_save_non_dict_json_returns_empty(self, monkeypatch, caplog):
        """extract_and_save 的 data.get 在 try 块外，非 dict 响应同样需防御。"""
        store = _enabled_store()
        _patch_httpx(monkeypatch, {
            "/memory/extraction/batch-extract": _FakeResponse(200, ["oops"]),
        })
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            result = await store.extract_and_save("s1", [{"role": "user", "content": "hi"}])
        assert result == {"extracted": 0, "saved": 0, "errors": []}
        assert store.stats()["extraction_failed"] == 1
        assert any("non-dict response body" in r.message for r in caplog.records)

    async def test_recall_layered_non_dict_json_falls_back(self, monkeypatch, caplog):
        store = _enabled_store()
        _patch_httpx(monkeypatch, {"/memory/recall/auto": _FakeResponse(200, ["oops"])})

        async def _fake_recall(query):
            return ""

        monkeypatch.setattr(store, "recall", _fake_recall)
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            result = await store.recall_layered("q")
        assert result["profile"] == ""  # 降级到普通 recall，不抛异常
        assert store.stats()["recall_layered_failed"] == 1
        assert store.stats()["recall_layered_fallback"] == 1
        assert any("non-dict response body" in r.message for r in caplog.records)


class TestSdkMigration:
    """G7：graph/extraction 经 SDK 公开 request() 透传后，第一阶段语义保持不变。"""

    def _mock_client(self, store, result=None, side_effect=None):
        """用 mock SDK client 替换 _client：_sdk_request 走公开 client.request()。"""
        client = SimpleNamespace(
            request=AsyncMock(return_value=result, side_effect=side_effect)
        )
        store._client = client
        return client

    async def test_graph_query_success_normalizes_neighbors(self):
        store = _enabled_store()
        client = self._mock_client(store, result={
            "neighbors": [
                {"entity_name": "张三", "relation_type": "knows", "confidence": 0.9},
            ],
        })
        result = await store.graph_query("张三")
        assert result == [
            {"entity": "张三", "relation": "knows", "target": "张三", "weight": 0.9},
        ]
        args = client.request.await_args
        assert args.args == ("GET", "/memory/graph/query")
        assert args.kwargs["params"] == {"q": "张三"}

    async def test_graph_query_4xx_no_retry_returns_empty(self, caplog):
        from agent_memory import exceptions as sdk_exc

        store = _enabled_store()
        client = self._mock_client(
            store, side_effect=sdk_exc.HTTPError(401, "Invalid or revoked API key")
        )
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert await store.graph_query("张三") == []
        assert client.request.await_count == 1  # 4xx 不重试
        assert store.stats()["graph_query_failed"] == 1
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert any("401" in m and "Invalid or revoked API key" in m for m in errors)

    async def test_graph_query_5xx_retries_then_succeeds(self, monkeypatch):
        from agent_memory import exceptions as sdk_exc

        monkeypatch.setattr(rm_module, "_RETRY_BACKOFFS", (0.01, 0.02))
        store = _enabled_store()
        client = self._mock_client(store, side_effect=[
            sdk_exc.HTTPError(500, "boom"),
            {"neighbors": []},
        ])
        assert await store.graph_query("张三") == []
        assert client.request.await_count == 2
        assert store.stats()["graph_query_failed"] == 0

    async def test_graph_query_non_list_neighbors_returns_empty(self, caplog):
        store = _enabled_store()
        self._mock_client(store, result={"neighbors": "oops"})
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert await store.graph_query("张三") == []
        assert store.stats()["graph_query_failed"] == 1
        assert any("'neighbors' is not a list" in r.message for r in caplog.records)

    async def test_graph_query_skips_non_dict_neighbor(self, caplog):
        store = _enabled_store()
        self._mock_client(store, result={
            "neighbors": [
                "bad-entry",
                {"entity_name": "张三", "relation_type": "knows", "confidence": 0.9},
            ],
        })
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            result = await store.graph_query("张三")
        assert result == [
            {"entity": "张三", "relation": "knows", "target": "张三", "weight": 0.9},
        ]
        assert store.stats()["graph_query_failed"] == 0  # 跳过单条不计入失败
        assert any("skipping non-dict neighbor" in r.message for r in caplog.records)

    async def test_graph_ingest_degraded_signal_preserved(self, caplog):
        store = _enabled_store()
        self._mock_client(store, result={
            "degraded": True, "entities_extracted": 1, "relations_created": 0,
        })
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            result = await store.graph_ingest("张三认识李四")
        assert result == {"entities_extracted": 1, "relations_created": 0}
        assert any("degrade_reason=degraded" in r.message for r in caplog.records)

    async def test_graph_ingest_http_error_returns_empty(self, caplog):
        from agent_memory import exceptions as sdk_exc

        store = _enabled_store()
        self._mock_client(store, side_effect=sdk_exc.HTTPError(503, "unavailable"))
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            result = await store.graph_ingest("张三认识李四")
        assert result == {"entities_extracted": 0, "relations_created": 0}
        assert store.stats()["graph_ingest_failed"] == 1
        assert any(
            "server error: HTTP 503" in r.message for r in caplog.records
        )

    async def test_extract_and_save_via_sdk_request(self):
        store = _enabled_store()
        client = self._mock_client(store, result={
            "variables": [{"key": "城市", "value": "杭州"}],
            "facts": ["用户住在杭州"],
            "preferences": [],
            "plans": [],
        })
        store._client.remember = AsyncMock(return_value=True)
        store._client.remember_fragment = AsyncMock(return_value={"id": 1})
        result = await store.extract_and_save("s1", [{"role": "user", "content": "hi"}])
        assert result["extracted"] == 2 and result["saved"] == 2
        assert result["errors"] == []
        first = client.request.await_args_list[0]
        assert first.args == ("POST", "/memory/extraction/batch-extract")
        assert first.kwargs["json"]["session_id"] == "s1"

    async def test_fallback_to_private_transport_when_no_public_request(
        self, monkeypatch, caplog
    ):
        """旧版 SDK（无公开 request()）：回退 _transport.request 且首次告警。"""
        monkeypatch.setattr(rm_module, "_SDK_TRANSPORT_FALLBACK_WARNED", False)
        store = _enabled_store()
        transport = SimpleNamespace(
            request=AsyncMock(return_value={"neighbors": []})
        )
        store._client = SimpleNamespace(_transport=transport)
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert await store.graph_query("张三") == []
        assert transport.request.await_count == 1  # 确实走了私有传输层
        assert any(
            "回退私有传输层" in r.getMessage()
            for r in caplog.records if r.levelno == logging.WARNING
        )
        # 每进程仅告警一次：二次调用不再重复
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert await store.graph_query("李四") == []
        assert not any(
            "回退私有传输层" in r.getMessage() for r in caplog.records
        )


class TestHybridRecall:
    """G5：混合搜索召回接入 + 失败自动降级单路语义召回。"""

    def _hybrid_store(self, result=None, side_effect=None, **cfg_overrides):
        """开启混合搜索的 store + mock 公开 request() + 语义召回兜底。"""
        store = _enabled_store(enable_hybrid_search=True, **cfg_overrides)
        client = SimpleNamespace(
            request=AsyncMock(return_value=result, side_effect=side_effect),
            recall_context=AsyncMock(return_value="语义召回兜底"),
        )
        store._client = client
        return store, client

    async def test_flag_off_uses_semantic_path(self):
        store = _enabled_store()  # 默认 enable_hybrid_search=False
        client = AsyncMock()
        client.recall_context.return_value = "单路召回"
        store._client = client
        assert await store.recall("q") == "单路召回"
        client.recall_context.assert_awaited_once()
        s = store.stats()
        assert s["hybrid_total"] == 0 and s["recall_total"] == 1

    async def test_hybrid_success_returns_joined_context(self):
        store, client = self._hybrid_store(result={
            "success": True,
            "fragments": [
                {"content": "用户住在杭州"},
                {"content": "喜欢羊肉面"},
                {"content": "   "},  # 空内容过滤
            ],
        })
        result = await store.recall("我住哪？晚饭吃什么？")
        assert result == "用户住在杭州\n喜欢羊肉面"
        args = client.request.await_args
        assert args.args == ("POST", "/memory/hybrid-search")
        payload = args.kwargs["json"]
        assert payload["query"] == "我住哪？晚饭吃什么？" and payload["top_k"] == 5
        # 分页字段与 HybridSearchRequest 契约对齐：首页 + limit 与 top_k 一致
        assert payload["offset"] == 0 and payload["limit"] == payload["top_k"]
        store._client.recall_context.assert_not_awaited()
        s = store.stats()
        assert s["hybrid_total"] == 1 and s["hybrid_failed"] == 0
        assert s["hybrid_fallback"] == 0 and s["recall_total"] == 0

    async def test_hybrid_result_truncated_to_max_chars(self):
        store, _ = self._hybrid_store(
            result={"fragments": [{"content": "长" * 300}]},
            recall_max_chars=200,
        )
        result = await store.recall("q")
        assert len(result) == 200 and result.endswith("...(截断)")

    async def test_hybrid_4xx_falls_back_no_retry(self, caplog):
        from agent_memory import exceptions as sdk_exc

        store, client = self._hybrid_store(
            side_effect=sdk_exc.HTTPError(422, "bad request")
        )
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert await store.recall("q") == "语义召回兜底"
        assert client.request.await_count == 1  # 4xx 不重试
        s = store.stats()
        assert s["hybrid_failed"] == 1 and s["hybrid_fallback"] == 1
        assert s["recall_total"] == 1  # 降级路径计入单路召回计数

    async def test_hybrid_5xx_retries_then_falls_back(self, monkeypatch):
        from agent_memory import exceptions as sdk_exc

        monkeypatch.setattr(rm_module, "_RETRY_BACKOFFS", (0.01,))
        store, client = self._hybrid_store(
            side_effect=sdk_exc.HTTPError(503, "down")
        )
        assert await store.recall("q") == "语义召回兜底"
        assert client.request.await_count == 2  # 1 次 + 1 次重试
        s = store.stats()
        assert s["hybrid_failed"] == 1 and s["hybrid_fallback"] == 1

    async def test_hybrid_timeout_budget_independent_of_remote_timeout(self):
        # remote_timeout 故意小于请求耗时；混合搜索走独立预算仍成功
        store, client = self._hybrid_store(
            remote_timeout=0.05, hybrid_search_timeout=5.0,
        )

        async def _slow_ok(*args, **kwargs):
            await asyncio.sleep(0.1)
            return {"fragments": [{"content": "命中"}]}

        client.request = AsyncMock(side_effect=_slow_ok)
        assert await store.recall("q") == "命中"
        assert store.stats()["hybrid_fallback"] == 0

    async def test_hybrid_timeout_falls_back(self):
        store, client = self._hybrid_store(hybrid_search_timeout=0.05)

        async def _hang(*args, **kwargs):
            await asyncio.sleep(1.0)

        client.request = AsyncMock(side_effect=_hang)
        assert await store.recall("q") == "语义召回兜底"
        s = store.stats()
        assert s["hybrid_failed"] == 1 and s["hybrid_fallback"] == 1

    async def test_hybrid_non_dict_response_falls_back(self, caplog):
        store, _ = self._hybrid_store(result=["oops"])
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            assert await store.recall("q") == "语义召回兜底"
        assert any("non-dict response body" in r.message for r in caplog.records)
        s = store.stats()
        assert s["hybrid_failed"] == 1 and s["hybrid_fallback"] == 1

    async def test_hybrid_empty_results_falls_back_without_failed(self):
        # 空结果（如 FTS 索引未建）回退但不计入 failed
        store, _ = self._hybrid_store(result={"success": True, "fragments": []})
        assert await store.recall("q") == "语义召回兜底"
        s = store.stats()
        assert s["hybrid_failed"] == 0 and s["hybrid_fallback"] == 1

    async def test_weights_sent_only_when_configured(self):
        store, client = self._hybrid_store(
            result={"fragments": [{"content": "x"}]},
            hybrid_alpha=0.6, hybrid_delta=0.2,
        )
        await store.recall("q")
        payload = client.request.await_args.kwargs["json"]
        assert payload["alpha"] == 0.6 and payload["delta"] == 0.2
        assert "beta" not in payload and "gamma" not in payload

    async def test_weights_omitted_by_default(self):
        store, client = self._hybrid_store(
            result={"fragments": [{"content": "x"}]}
        )
        await store.recall("q")
        payload = client.request.await_args.kwargs["json"]
        assert not any(k in payload for k in ("alpha", "beta", "gamma", "delta"))


class TestLifecycleDecommission:
    """改造 4：定时治理已下线，仅保留只读观测。"""

    def test_governance_trigger_methods_removed(self):
        store = RemoteMemoryStore()
        assert not hasattr(store, "run_lifecycle_maintenance")
        assert not hasattr(store, "detect_memory_conflicts")

    async def test_get_lifecycle_stats_readonly(self, monkeypatch):
        store = _enabled_store()
        _patch_httpx(monkeypatch, {
            "/memory/lifecycle/stats": _FakeResponse(200, {
                "success": True, "total": 10, "cold": 2,
            }),
        })
        stats = await store.get_lifecycle_stats()
        assert stats["total"] == 10
        assert store.stats()["lifecycle_total"] == 1

    async def test_get_lifecycle_stats_disabled_returns_empty(self):
        store = RemoteMemoryStore()
        assert await store.get_lifecycle_stats() == {}

    async def test_get_lifecycle_stats_failure_degrades_empty(self, monkeypatch):
        import httpx

        monkeypatch.setattr(rm_module, "_RETRY_BACKOFFS", (0.01,))
        store = _enabled_store()
        _patch_httpx(monkeypatch, {
            "/memory/lifecycle/stats": httpx.ConnectError("refused"),
        })
        assert await store.get_lifecycle_stats() == {}
        assert store.stats()["lifecycle_failed"] == 1

    async def test_get_resilience_status_flags_open_breaker(self, monkeypatch, caplog):
        store = _enabled_store()
        _patch_httpx(monkeypatch, {
            "/system/llm/resilience": _FakeResponse(200, {
                "success": True,
                "circuit_breakers": {"openai": {"state": "open"}},
                "retry_queue": {"depth": 0},
            }),
        })
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            data = await store.get_resilience_status()
        assert data["success"] is True
        assert any("degrade_reason=circuit_open" in r.getMessage() for r in caplog.records)

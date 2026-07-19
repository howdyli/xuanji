"""Unit tests for xiaopaw.llm (model_router + aliyun_llm).

All tests based on real code. No API keys or external services required.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from xiaopaw.llm.model_router import (
    ModelConfig,
    ModelRouter,
    ModelStats,
    RoutingStrategy,
    TaskType,
)
from xiaopaw.llm.aliyun_llm import (
    ENDPOINTS,
    _DEFAULT_TOOL_RESULT_MAX_CHARS,
    _normalize_mcp_tool_arguments,
    _truncate_tool_results,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers — singleton-safe ModelRouter fixture
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def router():
    """Return a fresh ModelRouter with cleared internal state.

    ModelRouter is a singleton via __new__; we bypass the guard by
    directly resetting internal dicts so each test starts clean.
    """
    r = ModelRouter()
    r._models.clear()
    r._task_routes.clear()
    r._stats.clear()
    r._round_robin_idx.clear()
    r._default_model = None
    r._default_strategy = RoutingStrategy.COST_FIRST
    r._fallback_chain.clear()
    yield r
    # no teardown needed — next fixture call will clear again


def _mc(name: str, **kw) -> ModelConfig:
    """Shorthand factory for ModelConfig."""
    return ModelConfig(name=name, **kw)


# ═══════════════════════════════════════════════════════════════════════════
# model_router.py — ModelConfig, ModelStats
# ═══════════════════════════════════════════════════════════════════════════


class TestModelConfig:
    def test_display_name_defaults_to_name(self):
        c = ModelConfig(name="deepseek-chat")
        assert c.display_name == "deepseek-chat"

    def test_display_name_explicit(self):
        c = ModelConfig(name="deepseek-chat", display_name="DS Chat")
        assert c.display_name == "DS Chat"

    def test_default_values(self):
        c = ModelConfig(name="m")
        assert c.provider == "deepseek"
        assert c.enabled is True
        assert c.healthy is True
        assert c.weight == 100


class TestModelStats:
    def test_avg_latency_no_calls(self):
        s = ModelStats()
        assert s.avg_latency_ms == 0.0

    def test_avg_latency_with_calls(self):
        s = ModelStats(successful_calls=3, total_latency_ms=900.0)
        assert s.avg_latency_ms == 300.0

    def test_success_rate_no_calls(self):
        s = ModelStats()
        assert s.success_rate == 1.0

    def test_success_rate_mixed(self):
        s = ModelStats(total_calls=10, successful_calls=7)
        assert s.success_rate == 0.7


# ═══════════════════════════════════════════════════════════════════════════
# model_router.py — ModelRouter core
# ═══════════════════════════════════════════════════════════════════════════


class TestRouterRegisterAndAvailable:
    def test_register_and_list(self, router):
        router.register_model(_mc("a"))
        assert "a" in router.get_available_models()

    def test_unregister(self, router):
        router.register_model(_mc("a"))
        router.unregister_model("a")
        assert "a" not in router.get_available_models()

    def test_mark_unhealthy_removes_from_available(self, router):
        router.register_model(_mc("a"))
        router.mark_model_unhealthy("a", "test")
        assert "a" not in router.get_available_models()

    def test_mark_healthy_restores(self, router):
        router.register_model(_mc("a"))
        router.mark_model_unhealthy("a")
        router.mark_model_healthy("a")
        assert "a" in router.get_available_models()

    def test_disabled_model_excluded(self, router):
        router.register_model(_mc("a", enabled=False))
        assert "a" not in router.get_available_models()


class TestSelectBest:
    def test_cost_first(self, router):
        router.register_model(_mc("cheap", cost_per_1k_tokens=0.001))
        router.register_model(_mc("expensive", cost_per_1k_tokens=0.01))
        chosen = router._select_best(
            ["cheap", "expensive"], RoutingStrategy.COST_FIRST
        )
        assert chosen == "cheap"

    def test_quality_first(self, router):
        router.register_model(_mc("low", quality_score=5.0))
        router.register_model(_mc("high", quality_score=9.5))
        chosen = router._select_best(
            ["low", "high"], RoutingStrategy.QUALITY_FIRST
        )
        assert chosen == "high"

    def test_latency_sensitive(self, router):
        router.register_model(_mc("fast", avg_latency_ms=200))
        router.register_model(_mc("slow", avg_latency_ms=5000))
        chosen = router._select_best(
            ["fast", "slow"], RoutingStrategy.LATENCY_SENSITIVE
        )
        assert chosen == "fast"

    def test_round_robin_cycles(self, router):
        router.register_model(_mc("a"))
        router.register_model(_mc("b"))
        cands = ["a", "b"]
        r1 = router._select_best(cands, RoutingStrategy.ROUND_ROBIN)
        r2 = router._select_best(cands, RoutingStrategy.ROUND_ROBIN)
        assert {r1, r2} == {"a", "b"}

    def test_priority_returns_first(self, router):
        router.register_model(_mc("a"))
        router.register_model(_mc("b"))
        chosen = router._select_best(["a", "b"], RoutingStrategy.PRIORITY)
        assert chosen == "a"

    def test_single_candidate(self, router):
        router.register_model(_mc("only"))
        chosen = router._select_best(["only"], RoutingStrategy.COST_FIRST)
        assert chosen == "only"


class TestFallback:
    def test_fallback_to_next(self, router):
        router.register_model(_mc("primary"))
        router.register_model(_mc("backup"))
        router.mark_model_unhealthy("primary")
        router._fallback_chain = ["primary", "backup"]
        fb = router._try_fallback("primary")
        assert fb is not None and fb.name == "backup"

    def test_no_fallback_available(self, router):
        router.register_model(_mc("only"))
        router.mark_model_unhealthy("only")
        router._fallback_chain = ["only"]
        fb = router._try_fallback("only")
        assert fb is None

    def test_fallback_skips_disabled(self, router):
        router.register_model(_mc("primary"))
        router.register_model(_mc("backup", enabled=False))
        router._fallback_chain = ["primary", "backup"]
        fb = router._try_fallback("primary")
        assert fb is None


class TestRecordCall:
    def test_success_increments(self, router):
        router.register_model(_mc("a"))
        router.record_call("a", success=True, latency_ms=100.0)
        s = router._stats["a"]
        assert s.total_calls == 1
        assert s.successful_calls == 1
        assert s.consecutive_failures == 0

    def test_failure_increments(self, router):
        router.register_model(_mc("a"))
        router.record_call("a", success=False, latency_ms=0)
        s = router._stats["a"]
        assert s.failed_calls == 1
        assert s.consecutive_failures == 1

    @patch.dict(os.environ, {"MODEL_UNHEALTHY_THRESHOLD": "3"})
    def test_auto_unhealthy_after_threshold(self, router):
        router.register_model(_mc("a"))
        for _ in range(3):
            router.record_call("a", success=False, latency_ms=0)
        assert router._models["a"].healthy is False

    def test_unknown_model_no_error(self, router):
        router.record_call("nonexistent", success=True, latency_ms=10)


class TestGetStats:
    def test_structure(self, router):
        router.register_model(_mc("a"))
        router._default_model = "a"
        stats = router.get_stats()
        assert stats["total_models"] == 1
        assert stats["default_model"] == "a"
        assert "a" in stats["models"]
        assert "success_rate" in stats["models"]["a"]

    def test_reset_all(self, router):
        router.register_model(_mc("a"))
        router.record_call("a", success=True, latency_ms=100)
        router.reset_stats()
        assert router._stats["a"].total_calls == 0

    def test_reset_single(self, router):
        router.register_model(_mc("a"))
        router.register_model(_mc("b"))
        router.record_call("a", success=True, latency_ms=100)
        router.record_call("b", success=True, latency_ms=200)
        router.reset_stats("a")
        assert router._stats["a"].total_calls == 0
        assert router._stats["b"].total_calls == 1


class TestInitFromConfig:
    def test_registers_models_and_routes(self, router):
        config = {
            "routing": {
                "default_model": "ds-chat",
                "default_strategy": "quality_first",
                "models": {
                    "ds-chat": {"provider": "deepseek", "quality_score": 7.5},
                    "ds-reasoner": {"provider": "deepseek", "quality_score": 9.0},
                },
                "task_routes": {
                    "orchestrator": ["ds-chat"],
                    "code_generation": ["ds-reasoner"],
                },
                "fallback_chain": ["ds-chat", "ds-reasoner"],
            }
        }
        router.init_from_config(config)
        assert "ds-chat" in router._models
        assert "ds-reasoner" in router._models
        assert router._default_model == "ds-chat"
        assert router._default_strategy == RoutingStrategy.QUALITY_FIRST
        assert TaskType.ORCHESTRATOR in router._task_routes
        assert router._fallback_chain == ["ds-chat", "ds-reasoner"]

    def test_unknown_task_type_skipped(self, router):
        config = {
            "routing": {
                "task_routes": {"nonexistent_type": ["model-a"]},
                "models": {"model-a": {}},
            }
        }
        router.init_from_config(config)
        # should not crash, unknown type logged and skipped


class TestGetLlm:
    def test_no_models_raises(self, router):
        with pytest.raises((ValueError, RuntimeError)):
            router.get_llm()

    @patch("xiaopaw.llm.model_router.os")
    def test_by_model_name(self, mock_os, router):
        mock_os.environ.get.return_value = "test-key"
        router.register_model(_mc("my-model", region="cn"))
        with patch("xiaopaw.llm.aliyun_llm.AliyunLLM.__init__", return_value=None) as m:
            router.get_llm(model_name="my-model")
            assert m.called
            assert m.call_args[1]["model"] == "my-model"


# ═══════════════════════════════════════════════════════════════════════════
# aliyun_llm.py — pure functions
# ═══════════════════════════════════════════════════════════════════════════


class TestEndpoints:
    def test_four_regions(self):
        assert len(ENDPOINTS) == 4
        assert "deepseek" in ENDPOINTS
        assert "cn" in ENDPOINTS
        assert "intl" in ENDPOINTS
        assert "finance" in ENDPOINTS


class TestNormalizeMcpToolArguments:
    def test_none_string_removed(self):
        tc = [{"function": {"arguments": '{"path": "None", "name": "test"}'}}]
        result = _normalize_mcp_tool_arguments(tc)
        args = json.loads(result[0]["function"]["arguments"])
        assert "path" not in args
        assert args["name"] == "test"

    def test_null_string_removed(self):
        tc = [{"function": {"arguments": '{"x": "null"}'}}]
        result = _normalize_mcp_tool_arguments(tc)
        args = json.loads(result[0]["function"]["arguments"])
        assert "x" not in args

    def test_true_string_converted(self):
        tc = [{"function": {"arguments": '{"verbose": "True"}'}}]
        result = _normalize_mcp_tool_arguments(tc)
        args = json.loads(result[0]["function"]["arguments"])
        assert args["verbose"] is True

    def test_false_string_converted(self):
        tc = [{"function": {"arguments": '{"debug": "False"}'}}]
        result = _normalize_mcp_tool_arguments(tc)
        args = json.loads(result[0]["function"]["arguments"])
        assert args["debug"] is False

    def test_mcp_list_param_becomes_empty_list(self):
        tc = [{"function": {"arguments": '{"file_types": "None"}'}}]
        result = _normalize_mcp_tool_arguments(tc)
        args = json.loads(result[0]["function"]["arguments"])
        assert args["file_types"] == []

    def test_invalid_json_skipped(self):
        tc = [{"function": {"arguments": "{invalid}"}}]
        result = _normalize_mcp_tool_arguments(tc)
        assert result[0]["function"]["arguments"] == "{invalid}"

    def test_empty_list(self):
        assert _normalize_mcp_tool_arguments([]) == []

    def test_deep_copy_original_unchanged(self):
        tc = [{"function": {"arguments": '{"x": "None"}'}}]
        _normalize_mcp_tool_arguments(tc)
        original_args = json.loads(tc[0]["function"]["arguments"])
        assert "x" in original_args  # original not modified


class TestTruncateToolResults:
    def test_short_content_unchanged(self):
        msgs = [{"role": "tool", "content": "short"}]
        result = _truncate_tool_results(msgs, max_chars=1000)
        assert result[0]["content"] == "short"

    def test_long_content_truncated(self):
        msgs = [{"role": "tool", "content": "x" * 200}]
        result = _truncate_tool_results(msgs, max_chars=50)
        assert len(result[0]["content"]) < 200
        assert "截断" in result[0]["content"]

    def test_non_tool_messages_unchanged(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = _truncate_tool_results(msgs, max_chars=5)
        assert result[0]["content"] == "hello"
        assert result[1]["content"] == "hi"

    def test_default_max_chars_from_env(self):
        with patch.dict(os.environ, {"LLM_TOOL_RESULT_MAX_CHARS": "100"}):
            msgs = [{"role": "tool", "content": "a" * 200}]
            result = _truncate_tool_results(msgs)
            assert "截断" in result[0]["content"]


# ═══════════════════════════════════════════════════════════════════════════
# aliyun_llm.py — AliyunLLM instance methods (no API call)
# ═══════════════════════════════════════════════════════════════════════════


class TestAliyunLLMHelpers:
    @pytest.fixture
    def llm(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}):
            from xiaopaw.llm.aliyun_llm import AliyunLLM
            return AliyunLLM(model="deepseek-chat", region="deepseek")

    def test_context_window_long_model(self, llm):
        llm.model = "qwen-long"
        assert llm.get_context_window_size() == 200_000

    def test_context_window_plus_model(self, llm):
        llm.model = "qwen-plus"
        assert llm.get_context_window_size() == 131_072

    def test_context_window_default(self, llm):
        llm.model = "small-model"
        assert llm.get_context_window_size() == 8192

    def test_validate_messages_valid(self, llm):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
            {"role": "tool", "content": "t"},
        ]
        llm._validate_messages(msgs)  # no exception

    def test_validate_messages_invalid_role(self, llm):
        with pytest.raises(ValueError, match="invalid message role"):
            llm._validate_messages([{"role": "unknown", "content": "x"}])

    def test_supports_function_calling(self, llm):
        assert llm.supports_function_calling() is True

    def test_supports_stop_words(self, llm):
        assert llm.supports_stop_words() is True

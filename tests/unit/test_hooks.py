"""Unit tests for hook_framework (loader, registry, crew_adapter) + shared_hooks.

All tests based on real code. No external services required.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from xiaopaw.hook_framework.registry import (
    DenyReason,
    EventType,
    GuardrailDeny,
    HookContext,
    HookRegistry,
)
from xiaopaw.hook_framework.loader import HookLoader
from xiaopaw.hook_framework.crew_adapter import (
    CrewObservabilityAdapter,
    _truncate,
    get_current_adapter,
    set_current_adapter,
)


# ═══════════════════════════════════════════════════════════════════════════
# registry.py — EventType, HookContext, GuardrailDeny, HookRegistry
# ═══════════════════════════════════════════════════════════════════════════


class TestEventType:
    def test_all_seven_events(self):
        assert len(EventType) == 7

    def test_event_values(self):
        assert EventType.BEFORE_TURN.value == "before_turn"
        assert EventType.SESSION_END.value == "session_end"


class TestGuardrailDeny:
    def test_with_deny_reason_enum(self):
        e = GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "bad command")
        assert e.reason_code == "sandbox_violation"
        assert "bad command" in str(e)

    def test_with_string_reason(self):
        e = GuardrailDeny("custom_reason", "detail")
        assert e.reason_code == "custom_reason"


class TestHookContext:
    def test_frozen_cannot_modify(self):
        ctx = HookContext(event_type=EventType.BEFORE_TURN)
        with pytest.raises(Exception):
            ctx.agent_id = "changed"

    def test_tool_input_is_readonly(self):
        ctx = HookContext(event_type=EventType.BEFORE_TOOL_CALL,
                          tool_input={"cmd": "ls"})
        with pytest.raises(TypeError):
            ctx.tool_input["new_key"] = "value"

    def test_metadata_is_readonly(self):
        ctx = HookContext(event_type=EventType.AFTER_TURN,
                          metadata={"key": "val"})
        with pytest.raises(TypeError):
            ctx.metadata["new"] = "x"

    def test_default_values(self):
        ctx = HookContext(event_type=EventType.BEFORE_TURN)
        assert ctx.agent_id == ""
        assert ctx.tool_name == ""
        assert ctx.success is True
        assert ctx.turn_number == 0


class TestHookRegistry:
    def test_register_and_count(self):
        reg = HookRegistry()
        reg.register(EventType.BEFORE_TURN, lambda ctx: None, name="h1")
        assert reg.handler_count(EventType.BEFORE_TURN) == 1

    def test_dispatch_calls_all_handlers(self):
        reg = HookRegistry()
        calls = []
        reg.register(EventType.BEFORE_TURN, lambda ctx: calls.append("a"))
        reg.register(EventType.BEFORE_TURN, lambda ctx: calls.append("b"))
        ctx = HookContext(event_type=EventType.BEFORE_TURN)
        reg.dispatch(EventType.BEFORE_TURN, ctx)
        assert calls == ["a", "b"]

    def test_dispatch_swallows_exceptions(self):
        reg = HookRegistry()
        calls = []
        reg.register(EventType.BEFORE_TURN, lambda ctx: 1 / 0)
        reg.register(EventType.BEFORE_TURN, lambda ctx: calls.append("ok"))
        ctx = HookContext(event_type=EventType.BEFORE_TURN)
        reg.dispatch(EventType.BEFORE_TURN, ctx)
        assert calls == ["ok"]  # second handler still runs

    def test_dispatch_gate_propagates_deny(self):
        reg = HookRegistry()
        def deny_handler(ctx):
            raise GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "blocked")
        reg.register(EventType.BEFORE_TOOL_CALL, deny_handler)
        ctx = HookContext(event_type=EventType.BEFORE_TOOL_CALL)
        with pytest.raises(GuardrailDeny):
            reg.dispatch_gate(EventType.BEFORE_TOOL_CALL, ctx)

    def test_dispatch_gate_swallows_non_deny(self):
        reg = HookRegistry()
        reg.register(EventType.BEFORE_TOOL_CALL, lambda ctx: 1 / 0)
        ctx = HookContext(event_type=EventType.BEFORE_TOOL_CALL)
        reg.dispatch_gate(EventType.BEFORE_TOOL_CALL, ctx)  # should not raise

    def test_dispatch_gate_fail_closed_converts_error_to_deny(self):
        reg = HookRegistry()
        def broken_handler(ctx):
            raise RuntimeError("internal bug")
        reg.register(EventType.BEFORE_TOOL_CALL, broken_handler,
                     name="sandbox", fail_closed=True)
        ctx = HookContext(event_type=EventType.BEFORE_TOOL_CALL)
        with pytest.raises(GuardrailDeny, match="fail-closed"):
            reg.dispatch_gate(EventType.BEFORE_TOOL_CALL, ctx)

    def test_dispatch_gate_fail_open_swallows_error(self):
        reg = HookRegistry()
        reg.register(EventType.BEFORE_TOOL_CALL, lambda ctx: 1 / 0,
                     fail_closed=False)
        ctx = HookContext(event_type=EventType.BEFORE_TOOL_CALL)
        reg.dispatch_gate(EventType.BEFORE_TOOL_CALL, ctx)  # no raise

    def test_dispatch_gate_stops_on_first_deny(self):
        reg = HookRegistry()
        calls = []
        def deny_handler(ctx):
            raise GuardrailDeny(DenyReason.PERMISSION_DENIED, "no")
        reg.register(EventType.BEFORE_TOOL_CALL, deny_handler)
        reg.register(EventType.BEFORE_TOOL_CALL, lambda ctx: calls.append("after"))
        ctx = HookContext(event_type=EventType.BEFORE_TOOL_CALL)
        with pytest.raises(GuardrailDeny):
            reg.dispatch_gate(EventType.BEFORE_TOOL_CALL, ctx)
        assert calls == []  # second handler not called

    def test_summary(self):
        reg = HookRegistry()
        reg.register(EventType.BEFORE_TURN, lambda ctx: None, name="log_handler")
        s = reg.summary()
        assert "before_turn" in s
        assert "log_handler" in s["before_turn"]


# ═══════════════════════════════════════════════════════════════════════════
# loader.py — HookLoader YAML loading + handler resolution
# ═══════════════════════════════════════════════════════════════════════════


class TestHookLoader:
    @pytest.fixture
    def hooks_dir(self, tmp_path):
        """Create a minimal hooks directory with YAML + handler modules."""
        # Handler module
        (tmp_path / "my_obs.py").write_text(textwrap.dedent("""\
            def on_turn(ctx):
                pass
            def on_llm(ctx):
                pass
        """))
        # Strategy module
        (tmp_path / "my_gate.py").write_text(textwrap.dedent("""\
            class MyGate:
                def __init__(self):
                    self.calls = []
                def check(self, ctx):
                    self.calls.append("checked")
        """))
        # YAML
        config = {
            "hooks": {
                "BEFORE_TURN": [{"handler": "my_obs.on_turn"}],
                "BEFORE_LLM": [{"handler": "my_obs.on_llm"}],
            },
            "strategies": [
                {
                    "name": "my_gate",
                    "class": "my_gate.MyGate",
                    "config": {},
                    "hooks": {"BEFORE_TOOL_CALL": "check"},
                }
            ],
        }
        (tmp_path / "hooks.yaml").write_text(yaml.dump(config))
        return tmp_path

    def test_load_from_directory_registers_handlers(self, hooks_dir):
        reg = HookRegistry()
        loader = HookLoader(reg)
        loader.load_from_directory(hooks_dir)
        assert reg.handler_count(EventType.BEFORE_TURN) == 1
        assert reg.handler_count(EventType.BEFORE_LLM) == 1
        assert reg.handler_count(EventType.BEFORE_TOOL_CALL) == 1

    def test_strategies_instantiated(self, hooks_dir):
        reg = HookRegistry()
        loader = HookLoader(reg)
        loader.load_from_directory(hooks_dir)
        assert "my_gate" in loader.strategies

    def test_missing_yaml_no_error(self, tmp_path):
        reg = HookRegistry()
        loader = HookLoader(reg)
        loader.load_from_directory(tmp_path / "nonexistent")
        assert reg.handler_count(EventType.BEFORE_TURN) == 0

    def test_invalid_handler_ref_skipped(self, tmp_path):
        (tmp_path / "hooks.yaml").write_text(yaml.dump({
            "hooks": {"BEFORE_TURN": [{"handler": "bad_ref_no_dot"}]},
        }))
        reg = HookRegistry()
        loader = HookLoader(reg)
        loader.load_from_directory(tmp_path)
        assert reg.handler_count(EventType.BEFORE_TURN) == 0

    def test_path_traversal_blocked(self, tmp_path):
        (tmp_path / "hooks.yaml").write_text(yaml.dump({
            "hooks": {"BEFORE_TURN": [{"handler": "../etc/passwd.evil"}]},
        }))
        reg = HookRegistry()
        loader = HookLoader(reg)
        loader.load_from_directory(tmp_path)
        assert reg.handler_count(EventType.BEFORE_TURN) == 0

    def test_load_two_layers(self, tmp_path):
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / "g_obs.py").write_text("def h(ctx): pass\n")
        (global_dir / "hooks.yaml").write_text(yaml.dump({
            "hooks": {"BEFORE_TURN": [{"handler": "g_obs.h"}]},
        }))

        ws_dir = tmp_path / "workspace"
        ws_hooks = ws_dir / "hooks"
        ws_hooks.mkdir(parents=True)
        (ws_hooks / "w_obs.py").write_text("def h(ctx): pass\n")
        (ws_hooks / "hooks.yaml").write_text(yaml.dump({
            "hooks": {"AFTER_TURN": [{"handler": "w_obs.h"}]},
        }))

        reg = HookRegistry()
        loader = HookLoader(reg)
        loader.load_two_layers(global_dir, ws_dir)
        assert reg.handler_count(EventType.BEFORE_TURN) == 1
        assert reg.handler_count(EventType.AFTER_TURN) == 1

    def test_hooks_section_loaded_before_strategies(self, hooks_dir):
        """Verify hooks section handlers are registered before strategies."""
        reg = HookRegistry()
        loader = HookLoader(reg)
        loader.load_from_directory(hooks_dir)
        # BEFORE_TURN has hooks-section handler
        # BEFORE_TOOL_CALL has strategies-section handler
        # Both should be registered
        assert reg.handler_count(EventType.BEFORE_TURN) >= 1
        assert reg.handler_count(EventType.BEFORE_TOOL_CALL) >= 1

    def test_deps_injection(self, tmp_path):
        """Dependencies are resolved and injected into strategy constructor."""
        (tmp_path / "dep_mod.py").write_text(textwrap.dedent("""\
            class Dep:
                pass
            class Consumer:
                def __init__(self, dep=None):
                    self.dep = dep
                def check(self, ctx):
                    pass
        """))
        config = {
            "strategies": [
                {"name": "dep", "class": "dep_mod.Dep", "config": {}, "hooks": {}},
                {
                    "name": "consumer",
                    "class": "dep_mod.Consumer",
                    "config": {},
                    "deps": {"dep": "dep"},
                    "hooks": {"BEFORE_TOOL_CALL": "check"},
                },
            ],
        }
        (tmp_path / "hooks.yaml").write_text(yaml.dump(config))
        reg = HookRegistry()
        loader = HookLoader(reg)
        loader.load_from_directory(tmp_path)
        consumer = loader.strategies["consumer"]
        assert consumer.dep is loader.strategies["dep"]


# ═══════════════════════════════════════════════════════════════════════════
# crew_adapter.py — CrewObservabilityAdapter
# ═══════════════════════════════════════════════════════════════════════════


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_long_text_truncated(self):
        result = _truncate("x" * 100, 50)
        assert len(result) < 100
        assert "truncated" in result


class TestCrewAdapter:
    @pytest.fixture
    def adapter(self):
        reg = HookRegistry()
        return CrewObservabilityAdapter(reg, session_id="s-test")

    def test_on_turn_start_dispatches(self, adapter):
        calls = []
        adapter._registry.register(EventType.BEFORE_TURN, lambda ctx: calls.append(ctx))
        adapter.on_turn_start("hello", sender_id="user1")
        assert len(calls) == 1
        assert calls[0].turn_number == 1

    def test_turn_count_increments(self, adapter):
        adapter.on_turn_start()
        adapter.on_turn_start()
        assert adapter._turn_count == 2

    def test_on_before_tool_call_dispatches(self, adapter):
        calls = []
        adapter._registry.register(EventType.BEFORE_TOOL_CALL, lambda ctx: calls.append(ctx))
        adapter.on_before_tool_call("search", {"query": "test"})
        assert len(calls) == 1
        assert calls[0].tool_name == "search"

    def test_pending_deny_pattern(self, adapter):
        """GuardrailDeny from dispatch_gate stored in _pending_deny."""
        def deny_handler(ctx):
            raise GuardrailDeny(DenyReason.SANDBOX_VIOLATION, "blocked")
        adapter._registry.register(EventType.BEFORE_TOOL_CALL, deny_handler)
        adapter.on_before_tool_call("bad_tool", {})
        assert adapter._pending_deny is not None
        assert adapter._pending_deny.reason_code == "sandbox_violation"

    def test_step_callback_reraises_pending_deny(self, adapter):
        adapter._pending_deny = GuardrailDeny(DenyReason.PERMISSION_DENIED, "no access")
        cb = adapter.make_step_callback()
        step = MagicMock()
        step.output = "done"
        step.tool = ""
        with pytest.raises(GuardrailDeny):
            cb(step)
        assert adapter._pending_deny is None

    def test_task_callback_reraises_pending_deny(self, adapter):
        adapter._pending_deny = GuardrailDeny(DenyReason.BUDGET_EXCEEDED, "over")
        cb = adapter.make_task_callback()
        task = MagicMock()
        task.raw = "result"
        task.description = "main task"
        with pytest.raises(GuardrailDeny):
            cb(task)

    def test_cleanup_dispatches_session_end(self, adapter):
        calls = []
        adapter._registry.register(EventType.SESSION_END, lambda ctx: calls.append(ctx))
        adapter.cleanup()
        assert len(calls) == 1

    def test_cleanup_idempotent(self, adapter):
        calls = []
        adapter._registry.register(EventType.SESSION_END, lambda ctx: calls.append(ctx))
        adapter.cleanup()
        adapter.cleanup()
        assert len(calls) == 1  # only dispatched once

    def test_cleanup_raises_pending_deny(self, adapter):
        adapter._pending_deny = GuardrailDeny(DenyReason.LOOP_DETECTED, "loop")
        with pytest.raises(GuardrailDeny):
            adapter.cleanup()

    def test_on_after_tool_call(self, adapter):
        calls = []
        adapter._registry.register(EventType.AFTER_TOOL_CALL, lambda ctx: calls.append(ctx))
        adapter.on_after_tool_call("search", {"q": "x"}, "result text")
        assert len(calls) == 1
        assert calls[0].tool_name == "search"

    def test_dispatch_after_turn(self, adapter):
        calls = []
        adapter._registry.register(EventType.AFTER_TURN, lambda ctx: calls.append(ctx))
        adapter.dispatch_after_turn("some output")
        assert len(calls) == 1


class TestContextVar:
    def test_set_and_get_adapter(self):
        adapter = MagicMock()
        set_current_adapter(adapter)
        assert get_current_adapter() is adapter
        set_current_adapter(None)
        assert get_current_adapter() is None


# ═══════════════════════════════════════════════════════════════════════════
# shared_hooks — CostGuard
# ═══════════════════════════════════════════════════════════════════════════

from shared_hooks.cost_guard import CostGuard


class TestCostGuard:
    def _ctx(self, input_tokens=0, output_tokens=0):
        return HookContext(
            event_type=EventType.AFTER_TURN,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def test_under_budget_no_deny(self):
        guard = CostGuard(budget_usd=10.0)
        guard.after_turn_handler(self._ctx(input_tokens=100, output_tokens=50))

    def test_exceed_budget_raises_deny(self):
        guard = CostGuard(budget_usd=0.0001)
        with pytest.raises(GuardrailDeny, match="budget_exceeded"):
            guard.after_turn_handler(self._ctx(input_tokens=1000000, output_tokens=500000))

    def test_before_tool_blocks_when_over(self):
        guard = CostGuard(budget_usd=0.0001)
        # First call exceeds budget (catch the deny from after_turn)
        with pytest.raises(GuardrailDeny):
            guard.after_turn_handler(self._ctx(input_tokens=1000000, output_tokens=500000))
        # Now before_tool should also block since cost is already over
        ctx = HookContext(event_type=EventType.BEFORE_TOOL_CALL)
        with pytest.raises(GuardrailDeny, match="budget_exceeded"):
            guard.before_tool_handler(ctx)

    def test_negative_budget_raises(self):
        with pytest.raises(ValueError):
            CostGuard(budget_usd=-1.0)

    def test_get_metrics(self):
        guard = CostGuard(budget_usd=5.0)
        guard.after_turn_handler(self._ctx(input_tokens=100, output_tokens=200))
        m = guard.get_metrics()
        assert m["total_input_tokens"] == 100
        assert m["total_output_tokens"] == 200
        assert m["budget_usd"] == 5.0


# ═══════════════════════════════════════════════════════════════════════════
# shared_hooks — RetryTracker
# ═══════════════════════════════════════════════════════════════════════════

from shared_hooks.retry_tracker import RetryTracker


class TestRetryTracker:
    def _ctx(self, tool_name="search", success=True):
        return HookContext(
            event_type=EventType.AFTER_TOOL_CALL,
            tool_name=tool_name,
            success=success,
        )

    def test_success_no_retries(self):
        tracker = RetryTracker()
        tracker.after_tool_handler(self._ctx(success=True))
        m = tracker.get_metrics()
        assert m["total_retries"] == 0

    def test_consecutive_failures_counted(self):
        tracker = RetryTracker()
        for _ in range(3):
            tracker.after_tool_handler(self._ctx(success=False))
        m = tracker.get_metrics()
        assert m["active_failures"]["search"] == 3

    def test_successful_retry(self):
        tracker = RetryTracker()
        tracker.after_tool_handler(self._ctx(success=False))
        tracker.after_tool_handler(self._ctx(success=False))
        tracker.after_tool_handler(self._ctx(success=True))
        m = tracker.get_metrics()
        assert m["successful_retries"] == 1
        assert m["active_failures"] == {}

    def test_empty_tool_name_skipped(self):
        tracker = RetryTracker()
        ctx = HookContext(event_type=EventType.AFTER_TOOL_CALL, tool_name="")
        tracker.after_tool_handler(ctx)
        assert tracker.get_metrics()["total_retries"] == 0

    def test_metrics_retry_success_rate(self):
        tracker = RetryTracker()
        tracker.after_tool_handler(self._ctx(success=False))
        tracker.after_tool_handler(self._ctx(success=False))
        tracker.after_tool_handler(self._ctx(success=True))
        m = tracker.get_metrics()
        assert m["retry_success_rate"] > 0

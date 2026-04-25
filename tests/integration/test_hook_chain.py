"""IT-CHN-001 ~ IT-CHN-008: Full hook chain integration tests."""

from pathlib import Path

import pytest

from xiaopaw.hook_framework.loader import HookLoader
from xiaopaw.hook_framework.registry import EventType, GuardrailDeny, HookContext, HookRegistry

SHARED_HOOKS_DIR = Path(__file__).parent.parent.parent / "shared_hooks"


@pytest.fixture
def loaded_chain(tmp_path):
    registry = HookRegistry()
    loader = HookLoader(registry)
    loader.load_from_directory(SHARED_HOOKS_DIR, layer_name="global")
    return registry, loader


def _tool_ctx(tool_name="knowledge_search", tool_input=None):
    return HookContext(
        event_type=EventType.BEFORE_TOOL_CALL,
        tool_name=tool_name,
        tool_input=tool_input or {"query": "normal search"},
    )


def _turn_ctx(input_tokens=100, output_tokens=50, turn=1, output="result"):
    return HookContext(
        event_type=EventType.AFTER_TURN,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        turn_number=turn,
        metadata={"output": output, "model": "qwen-plus"},
    )


@pytest.mark.integration
class TestHookChain:
    def test_chn001_dispatch_fires_handlers(self, loaded_chain):
        registry, _ = loaded_chain
        ctx = HookContext(event_type=EventType.BEFORE_TURN, session_id="test")
        registry.dispatch(EventType.BEFORE_TURN, ctx)

    def test_chn002_dispatch_gate_fires_strategy_handlers(self, loaded_chain):
        registry, _ = loaded_chain
        registry.dispatch_gate(EventType.BEFORE_TOOL_CALL, _tool_ctx())

    def test_chn003_all_strategies_loaded(self, loaded_chain):
        _, loader = loaded_chain
        expected = {"audit_logger", "sandbox_guard", "permission_gate",
                    "cost_guard", "loop_detector", "retry_tracker"}
        assert expected == set(loader.strategies.keys())

    def test_chn004_after_turn_order_cost_before_loop(self, loaded_chain):
        registry, loader = loaded_chain
        cost = loader.strategies["cost_guard"]
        loop = loader.strategies["loop_detector"]
        registry.dispatch_gate(
            EventType.AFTER_TURN,
            _turn_ctx(input_tokens=100, output_tokens=50, output="unique1"),
        )
        assert cost.get_metrics()["total_input_tokens"] == 100
        assert loop.get_metrics()["total_turns"] == 1

    def test_chn005_before_tool_order_sandbox_permission_cost(self, loaded_chain):
        registry, loader = loaded_chain
        registry.dispatch_gate(EventType.BEFORE_TOOL_CALL, _tool_ctx())
        sandbox = loader.strategies["sandbox_guard"]
        perm = loader.strategies["permission_gate"]
        cost = loader.strategies["cost_guard"]
        assert sandbox.get_metrics()["total_violations"] == 0
        assert len(perm.decisions) == 1
        assert cost.get_metrics()["deny_count"] == 0

    def test_chn006_first_deny_stops_chain(self, loaded_chain):
        registry, loader = loaded_chain
        perm = loader.strategies["permission_gate"]
        with pytest.raises(GuardrailDeny):
            registry.dispatch_gate(
                EventType.BEFORE_TOOL_CALL,
                _tool_ctx(tool_input={"query": "../../etc/passwd"}),
            )
        assert len(perm.decisions) == 0

    def test_chn007_session_end_triggers_audit(self, loaded_chain, tmp_path):
        registry, loader = loaded_chain
        audit = loader.strategies["audit_logger"]
        audit._audit_file = tmp_path / "audit.jsonl"
        registry.dispatch(
            EventType.SESSION_END,
            HookContext(event_type=EventType.SESSION_END, session_id="test"),
        )
        assert (tmp_path / "audit.jsonl").exists()
        content = (tmp_path / "audit.jsonl").read_text()
        assert "session_summary" in content

    def test_chn008_after_tool_fires_retry_and_loop(self, loaded_chain):
        registry, loader = loaded_chain
        ctx = HookContext(
            event_type=EventType.AFTER_TOOL_CALL,
            tool_name="search",
            success=True,
            metadata={"tool_output": "result"},
        )
        registry.dispatch(EventType.AFTER_TOOL_CALL, ctx)
        retry = loader.strategies["retry_tracker"]
        loop = loader.strategies["loop_detector"]
        assert retry.get_metrics()["active_failures"] == {}
        assert loop.get_metrics()["total_tool_calls"] == 1

"""IT-ADP-001 ~ IT-ADP-006: Adapter + Registry + Strategies integration tests."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from xiaopaw.hook_framework.crew_adapter import CrewObservabilityAdapter
from xiaopaw.hook_framework.loader import HookLoader
from xiaopaw.hook_framework.registry import EventType, GuardrailDeny, HookContext, HookRegistry

SHARED_HOOKS_DIR = Path(__file__).parent.parent.parent / "shared_hooks"


@pytest.fixture
def adapter_chain(tmp_path):
    registry = HookRegistry()
    loader = HookLoader(registry)
    loader.load_from_directory(SHARED_HOOKS_DIR, layer_name="global")
    adapter = CrewObservabilityAdapter(registry, session_id="test_session")
    return adapter, registry, loader


@pytest.mark.integration
class TestAdapterIntegration:
    def test_adp_it001_before_llm_dispatches_events(self, adapter_chain):
        adapter, _, loader = adapter_chain
        adapter.on_before_llm(agent_role="XiaoPaw", messages=[])

    def test_adp_it002_before_tool_sandbox_blocks(self, adapter_chain):
        adapter, _, loader = adapter_chain
        adapter.on_before_tool_call(
            tool_name="reader", tool_input={"path": "../../etc/passwd"}
        )
        assert adapter._pending_deny is not None
        sandbox = loader.strategies["sandbox_guard"]
        assert sandbox.get_metrics()["total_violations"] >= 1

    def test_adp_it003_step_callback_with_cost(self, adapter_chain):
        adapter, registry, loader = adapter_chain
        cost = loader.strategies["cost_guard"]
        loop = loader.strategies["loop_detector"]
        step_cb = adapter.make_step_callback()
        step_cb(MagicMock(output="test result"))
        assert loop.get_metrics()["total_turns"] == 1
        assert cost.get_metrics()["estimated_cost_usd"] == 0.0

    def test_adp_it004_task_callback(self, adapter_chain):
        adapter, _, loader = adapter_chain
        collected = []
        registry = adapter._registry
        registry.register(EventType.TASK_COMPLETE, lambda ctx: collected.append(ctx))
        task_cb = adapter.make_task_callback()
        task_cb(MagicMock(raw="final output", description="do work"))
        assert len(collected) == 1

    def test_adp_it005_cleanup_triggers_audit(self, adapter_chain, tmp_path):
        adapter, _, loader = adapter_chain
        audit = loader.strategies["audit_logger"]
        audit._audit_file = tmp_path / "audit.jsonl"
        adapter.cleanup()
        assert (tmp_path / "audit.jsonl").exists()

    def test_adp_it006_full_lifecycle(self, adapter_chain):
        adapter, _, loader = adapter_chain
        adapter.on_before_llm(agent_role="Main", messages=[{"content": "hi"}])
        adapter.on_before_llm(agent_role="Main", messages=[{"content": "think"}])
        adapter.on_before_tool_call(
            tool_name="search", tool_input={"q": "safe query"}
        )
        adapter.on_after_tool_call(
            tool_name="search", tool_input={"q": "safe query"}, tool_result="found"
        )
        step_cb = adapter.make_step_callback()
        step_cb(MagicMock(output="step result"))
        adapter.on_before_llm(agent_role="Main", messages=[{"content": "next"}])
        step_cb(MagicMock(output="final step"))
        task_cb = adapter.make_task_callback()
        task_cb(MagicMock(raw="done", description="task"))
        adapter.cleanup()
        assert adapter._turn_count == 2

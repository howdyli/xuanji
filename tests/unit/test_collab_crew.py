"""Unit tests for the P3-1 multi-agent collaboration pipeline.

These build REAL CrewAI Agent/Task/Crew objects with an offline AliyunLLM
(constructed without network I/O), so they assert the actual pipeline
structure — agent roster, task chaining via ``context``, the final
``output_pydantic``, the tool-less invariant for planner/reviewer, and callback
forwarding — without ever calling an LLM.

The single-agent default path is guarded by the feature flag; these tests also
pin the flag default to off so the pipeline stays opt-in.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import yaml
from crewai import Agent, Process, Task

from xiaopaw.agents.collab_crew import TOOLLESS_ROLES, build_collab_crew
from xiaopaw.agents.main_crew import (
    MemoryAwareCrew,
    _build_role_label_map,
    _resolve_agent_role_label,
)
from xiaopaw.agents.models import MainTaskOutput
from xiaopaw.config.flags import FeatureFlags
from xiaopaw.hook_framework.crew_adapter import set_current_adapter
from xiaopaw.llm.aliyun_llm import AliyunLLM

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "xiaopaw" / "agents" / "config"


def _offline_llm(**_kwargs) -> AliyunLLM:
    """An AliyunLLM built without env/network — safe to construct in CI."""
    return AliyunLLM(model="deepseek-chat", region="deepseek", api_key="test-key")


def _load_cfg() -> tuple[dict, dict]:
    agents_cfg = yaml.safe_load((_CONFIG_DIR / "agents.yaml").read_text(encoding="utf-8"))
    tasks_cfg = yaml.safe_load((_CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8"))
    return agents_cfg, tasks_cfg


def _build_executor() -> tuple[Agent, Task]:
    """Mirror the production shape: an orchestrator agent + its task."""
    executor = Agent(
        role="xuanji 工作助手",
        goal="执行",
        backstory="bs",
        llm=_offline_llm(),
        tools=[],
    )
    main_task = Task(
        description="执行 {user_message}",
        expected_output="结果",
        agent=executor,
        output_pydantic=MainTaskOutput,
    )
    return executor, main_task


# ═══════════════════════════════════════════════════════════════════════════
# Feature flag: pipeline is opt-in
# ═══════════════════════════════════════════════════════════════════════════


class TestFlagDefault:
    def test_multi_agent_collab_default_off(self):
        assert FeatureFlags().enable_multi_agent_collab is False

    def test_flag_can_be_enabled(self):
        flags = FeatureFlags(enable_multi_agent_collab=True)
        assert flags.enable_multi_agent_collab is True


# ═══════════════════════════════════════════════════════════════════════════
# Config completeness: planner/reviewer + plan_task/review_task exist
# ═══════════════════════════════════════════════════════════════════════════


class TestCollabConfigs:
    def test_agent_configs_present(self):
        agents_cfg, _ = _load_cfg()
        for role in ("planner", "reviewer"):
            assert role in agents_cfg
            assert {"role", "goal", "backstory"} <= set(agents_cfg[role])

    def test_task_configs_present(self):
        _, tasks_cfg = _load_cfg()
        for name in ("plan_task", "review_task"):
            assert name in tasks_cfg
            assert {"description", "expected_output"} <= set(tasks_cfg[name])

    def test_plan_task_takes_user_message(self):
        _, tasks_cfg = _load_cfg()
        assert "{user_message}" in tasks_cfg["plan_task"]["description"]


# ═══════════════════════════════════════════════════════════════════════════
# build_collab_crew: real structure assertions
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildCollabCrew:
    def test_three_agents_in_order(self):
        agents_cfg, tasks_cfg = _load_cfg()
        executor, main_task = _build_executor()
        crew = build_collab_crew(
            executor_agent=executor,
            main_task=main_task,
            llm_factory=_offline_llm,
            agents_cfg=agents_cfg,
            tasks_cfg=tasks_cfg,
            output_pydantic=MainTaskOutput,
        )
        assert len(crew.agents) == 3
        # planner first, executor (the passed-in orchestrator) middle, reviewer last
        assert crew.agents[1] is executor
        assert crew.agents[0].role == agents_cfg["planner"]["role"]
        assert crew.agents[2].role == agents_cfg["reviewer"]["role"]

    def test_task_chain_wiring(self):
        agents_cfg, tasks_cfg = _load_cfg()
        executor, main_task = _build_executor()
        crew = build_collab_crew(
            executor_agent=executor,
            main_task=main_task,
            llm_factory=_offline_llm,
            agents_cfg=agents_cfg,
            tasks_cfg=tasks_cfg,
            output_pydantic=MainTaskOutput,
        )
        plan_task, mid_task, review_task = crew.tasks
        assert mid_task is main_task
        # main_task consumes the plan; review consumes the executor output
        assert mid_task.context == [plan_task]
        assert review_task.context == [main_task]

    def test_final_output_is_main_task_output(self):
        agents_cfg, tasks_cfg = _load_cfg()
        executor, main_task = _build_executor()
        crew = build_collab_crew(
            executor_agent=executor,
            main_task=main_task,
            llm_factory=_offline_llm,
            agents_cfg=agents_cfg,
            tasks_cfg=tasks_cfg,
            output_pydantic=MainTaskOutput,
        )
        assert crew.tasks[-1].output_pydantic is MainTaskOutput

    def test_process_is_sequential(self):
        agents_cfg, tasks_cfg = _load_cfg()
        executor, main_task = _build_executor()
        crew = build_collab_crew(
            executor_agent=executor,
            main_task=main_task,
            llm_factory=_offline_llm,
            agents_cfg=agents_cfg,
            tasks_cfg=tasks_cfg,
            output_pydantic=MainTaskOutput,
        )
        assert crew.process == Process.sequential

    def test_planner_and_reviewer_have_no_tools(self):
        agents_cfg, tasks_cfg = _load_cfg()
        executor, main_task = _build_executor()
        crew = build_collab_crew(
            executor_agent=executor,
            main_task=main_task,
            llm_factory=_offline_llm,
            agents_cfg=agents_cfg,
            tasks_cfg=tasks_cfg,
            output_pydantic=MainTaskOutput,
        )
        planner, _executor, reviewer = crew.agents
        assert not planner.tools
        assert not reviewer.tools
        # the tool-less invariant is named for both callers and tests
        assert TOOLLESS_ROLES == ("planner", "reviewer")

    def test_callbacks_forwarded(self):
        agents_cfg, tasks_cfg = _load_cfg()
        executor, main_task = _build_executor()
        step_cb = MagicMock()
        task_cb = MagicMock()
        crew = build_collab_crew(
            executor_agent=executor,
            main_task=main_task,
            llm_factory=_offline_llm,
            agents_cfg=agents_cfg,
            tasks_cfg=tasks_cfg,
            output_pydantic=MainTaskOutput,
            step_callback=step_cb,
            task_callback=task_cb,
        )
        assert crew.step_callback is step_cb
        assert crew.task_callback is task_cb

    def test_llm_factory_called_for_toolless_roles(self):
        agents_cfg, tasks_cfg = _load_cfg()
        executor, main_task = _build_executor()
        calls: list[dict] = []

        def _tracking_factory(**kwargs):
            calls.append(kwargs)
            return _offline_llm()

        build_collab_crew(
            executor_agent=executor,
            main_task=main_task,
            llm_factory=_tracking_factory,
            agents_cfg=agents_cfg,
            tasks_cfg=tasks_cfg,
            output_pydantic=MainTaskOutput,
        )
        # one LLM per tool-less role (planner + reviewer); executor brings its own
        assert len(calls) == 2
        assert all(c.get("task_type") == "orchestrator" for c in calls)


# ═══════════════════════════════════════════════════════════════════════════
# Role attribution: map role strings → canonical labels (observability)
# ═══════════════════════════════════════════════════════════════════════════


class TestRoleLabelMap:
    def test_build_map_covers_collab_roles(self):
        agents_cfg, _ = _load_cfg()
        m = _build_role_label_map(agents_cfg)
        assert m["xuanji 工作助手"] == "orchestrator"
        assert m["任务规划专家"] == "planner"
        assert m["质量审查专家"] == "reviewer"

    def test_build_map_skips_templated_roles(self):
        # skill_agent's role is templated ("{skill_name_upper} 执行专家") and must
        # not leak into the observability label map.
        agents_cfg, _ = _load_cfg()
        m = _build_role_label_map(agents_cfg)
        assert all("{" not in role_string for role_string in m)
        assert "skill_agent" not in m.values()

    def test_resolve_known_role(self):
        m = {"任务规划专家": "planner"}
        agent = SimpleNamespace(role="任务规划专家")
        assert _resolve_agent_role_label(agent, m) == "planner"

    def test_resolve_defaults_to_orchestrator(self):
        m = {"任务规划专家": "planner"}
        # None agent (direct LLM call) and unknown role both fall back.
        assert _resolve_agent_role_label(None, m) == "orchestrator"
        assert _resolve_agent_role_label(SimpleNamespace(role="???"), m) == "orchestrator"


# ═══════════════════════════════════════════════════════════════════════════
# before_llm_hook: executor-scoped memory + per-agent observability label
# ═══════════════════════════════════════════════════════════════════════════


def _make_crew(tmp_path) -> MemoryAwareCrew:
    return MemoryAwareCrew(
        session_id="s1",
        routing_key="p2p:web_u",
        user_message="hi",
        sender=MagicMock(),
        workspace_dir=tmp_path,
        ctx_dir=tmp_path / "ctx",
        history_all=[],
    )


def _ctx(role: str | None, messages: list | None = None) -> SimpleNamespace:
    agent = SimpleNamespace(role=role) if role is not None else None
    return SimpleNamespace(
        agent=agent,
        messages=messages if messages is not None else [],
        llm=None,
    )


class _RecordingAdapter:
    """Captures on_before_llm agent_role labels; other adapter calls are no-ops."""

    def __init__(self) -> None:
        self.roles: list[str] = []

    def on_before_llm(self, agent_role: str = "", messages=None, model: str = "") -> None:
        self.roles.append(agent_role)


class TestExecutorScopedHook:
    def test_planner_call_skips_restore_and_index(self, tmp_path):
        crew = _make_crew(tmp_path)
        crew.before_llm_hook(_ctx("任务规划专家", [{"role": "user", "content": "hi"}]))
        # Planner is not the executor: no session restore, no index bookkeeping.
        assert crew._session_loaded is False
        assert crew._last_msgs == []

    def test_reviewer_call_skips_restore_and_index(self, tmp_path):
        crew = _make_crew(tmp_path)
        crew.before_llm_hook(_ctx("质量审查专家", [{"role": "user", "content": "hi"}]))
        assert crew._session_loaded is False
        assert crew._last_msgs == []

    def test_orchestrator_call_restores_and_tracks(self, tmp_path):
        crew = _make_crew(tmp_path)
        ctx = _ctx(
            "xuanji 工作助手",
            [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}],
        )
        crew.before_llm_hook(ctx)
        assert crew._session_loaded is True
        assert crew._last_msgs is ctx.messages

    def test_direct_call_without_agent_treated_as_executor(self, tmp_path):
        # No agent on context (direct LLM call) → behaves exactly like before.
        crew = _make_crew(tmp_path)
        crew.before_llm_hook(_ctx(None, [{"role": "user", "content": "hi"}]))
        assert crew._session_loaded is True

    def test_adapter_labeled_per_agent(self, tmp_path):
        crew = _make_crew(tmp_path)
        rec = _RecordingAdapter()
        set_current_adapter(rec)
        try:
            crew.before_llm_hook(_ctx("任务规划专家", [{"role": "user", "content": "x"}]))
            crew.before_llm_hook(_ctx("xuanji 工作助手", [{"role": "user", "content": "x"}]))
            crew.before_llm_hook(_ctx("质量审查专家", [{"role": "user", "content": "x"}]))
        finally:
            set_current_adapter(None)
        assert rec.roles == ["planner", "orchestrator", "reviewer"]

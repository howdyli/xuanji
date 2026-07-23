"""Multi-Agent collaboration pipeline (P3-1 first increment).

Opt-in planner→executor→reviewer sequential crew, gated by
``FeatureFlags.enable_multi_agent_collab`` (default off). The executor is the
existing memory/skill-aware orchestrator agent; planner and reviewer are
lightweight LLM-only roles (no tools) that bookend it:

    planner  → decomposes the user request into an ordered plan
    executor → the orchestrator (has skill_loader + intermediate tools)
    reviewer → checks the executor output against the plan and produces the
               final user-facing reply (MainTaskOutput)

Task outputs chain via CrewAI ``context=[...]``:
    plan_task → main_task(context=[plan_task]) → review_task(context=[main_task])

The default single-agent path in ``MemoryAwareCrew.crew`` is untouched when the
flag is off, so this is backward compatible and low risk. The builder is a
pure function (agents/tasks are constructed from injected configs + an
``llm_factory``), which keeps it unit-testable without a live LLM.

Memory / observability integration (P3-1 second increment):
``MemoryAwareCrew.before_llm_hook`` resolves the *actual* calling agent
(orchestrator/planner/reviewer) via its role string, so langfuse/audit/EventBus
attribute each LLM call to the right role. Session restore, context
prune/compress and turn-indexing bookkeeping are gated to the executor
(orchestrator) only — the planner/reviewer are ephemeral per-turn reasoners that
neither own nor mutate the persisted conversation.
"""

from __future__ import annotations

from typing import Any, Callable

from crewai import Agent, Crew, Process, Task

# Roles that must not carry tools: they only reason over text (plan / review),
# never touch the sandbox or skills. Kept as a module constant so tests and
# callers agree on the invariant.
TOOLLESS_ROLES = ("planner", "reviewer")


def build_collab_crew(
    *,
    executor_agent: Agent,
    main_task: Task,
    llm_factory: Callable[..., Any],
    agents_cfg: dict[str, Any],
    tasks_cfg: dict[str, Any],
    output_pydantic: type,
    step_callback: Callable[..., Any] | None = None,
    task_callback: Callable[..., Any] | None = None,
    verbose: bool = False,
) -> Crew:
    """Build the planner→executor→reviewer sequential crew.

    Args:
        executor_agent: the already-built orchestrator (has tools + memory).
        main_task: the orchestrator's task; its ``context`` is wired to the
            planner output in place.
        llm_factory: callable returning an LLM for the tool-less roles; called
            as ``llm_factory(task_type="orchestrator")`` so it reuses the same
            routing as the executor.
        agents_cfg: parsed ``agents.yaml`` (must contain ``planner`` /
            ``reviewer``).
        tasks_cfg: parsed ``tasks.yaml`` (must contain ``plan_task`` /
            ``review_task``).
        output_pydantic: pydantic model for the reviewer's final output
            (``MainTaskOutput``), so ``run_and_index`` reads the reply uniformly.
        step_callback / task_callback: forwarded to the Crew (hook integration).
        verbose: forwarded to agents and crew.

    Returns:
        A CrewAI ``Crew`` with three agents and three chained tasks running in
        ``Process.sequential``.
    """
    planner = Agent(
        **agents_cfg["planner"],
        llm=llm_factory(task_type="orchestrator"),
        tools=[],
        verbose=verbose,
    )
    reviewer = Agent(
        **agents_cfg["reviewer"],
        llm=llm_factory(task_type="orchestrator"),
        tools=[],
        verbose=verbose,
    )

    plan_task = Task(**tasks_cfg["plan_task"], agent=planner)

    # Executor consumes the plan; reviewer consumes the executor output. Wiring
    # main_task.context in place keeps the orchestrator's existing config intact.
    main_task.context = [plan_task]

    review_task = Task(
        **tasks_cfg["review_task"],
        agent=reviewer,
        context=[main_task],
        output_pydantic=output_pydantic,
    )

    return Crew(
        agents=[planner, executor_agent, reviewer],
        tasks=[plan_task, main_task, review_task],
        process=Process.sequential,
        verbose=verbose,
        step_callback=step_callback,
        task_callback=task_callback,
    )

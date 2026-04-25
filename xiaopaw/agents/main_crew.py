"""MemoryAwareCrew: main agent with three-layer memory and hook integration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any

import yaml
from crewai import Agent, Crew, Process, Task
from crewai.agents.parser import AgentAction, AgentFinish
from crewai.hooks import LLMCallHookContext, before_llm_call
from crewai.project import CrewBase, agent, crew, task

from xiaopaw.hook_framework.crew_adapter import get_current_adapter

from xiaopaw.agents.models import MainTaskOutput
from xiaopaw.config.flags import FeatureFlags
from xiaopaw.llm.aliyun_llm import AliyunLLM
from xiaopaw.memory.bootstrap import build_bootstrap_prompt
from xiaopaw.memory.context_mgmt import (
    append_session_raw,
    load_session_ctx,
    maybe_compress,
    prune_tool_results,
    save_session_ctx,
)
from xiaopaw.memory.indexer import async_index_turn
from xiaopaw.models import SenderProtocol
from xiaopaw.session.models import MessageEntry
from xiaopaw.tools.intermediate_tool import IntermediateTool

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent / "config"
_DEFAULT_MAX_HISTORY_TURNS = 20

AgentFn = Callable[
    [str, list[MessageEntry], str, str, bool],
    Awaitable[str],
]


def _format_history(history: list[MessageEntry], max_turns: int = 20) -> str:
    if not history:
        return "（无历史记录）"
    tail = history[-(max_turns * 2):]
    was_truncated = len(history) > max_turns * 2
    lines: list[str] = []
    if was_truncated:
        lines.append(f"（仅显示最近 {max_turns} 轮，完整历史请使用 history_reader Skill）")
    for entry in tail:
        role_label = "用户" if entry.role == "user" else "助手"
        lines.append(f"{role_label}: {entry.content}")
    return "\n".join(lines)


def _make_step_callback(
    sender: SenderProtocol, routing_key: str
) -> Callable[[Any], Awaitable[None]]:
    async def _callback(step_output: Any) -> None:
        if isinstance(step_output, AgentAction) and step_output.thought:
            try:
                await sender.send_thinking(routing_key, step_output.thought[:200])
            except Exception:
                pass

        adapter = get_current_adapter()
        if not adapter:
            return

        if isinstance(step_output, AgentAction) and step_output.tool:
            adapter.on_after_tool_call(
                tool_name=step_output.tool,
                tool_input={"input": str(step_output.tool_input or "")[:500]},
                tool_result=str(getattr(step_output, "result", "") or "")[:500],
            )
        elif isinstance(step_output, AgentFinish):
            output = str(getattr(step_output, "output", "") or "")[:500]
            adapter.on_after_tool_call(
                tool_name="final_answer",
                tool_result=output,
            )

    return _callback


@CrewBase
class MemoryAwareCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(
        self,
        session_id: str,
        routing_key: str,
        user_message: str,
        sender: SenderProtocol,
        workspace_dir: Path,
        ctx_dir: Path,
        history_all: list[MessageEntry],
        db_dsn: str = "",
        max_history_turns: int = _DEFAULT_MAX_HISTORY_TURNS,
        sandbox_url: str = "",
        flags: FeatureFlags | None = None,
        verbose: bool = False,
    ) -> None:
        self.session_id = session_id
        self.routing_key = routing_key
        self.user_message = user_message
        self._sender = sender
        self._workspace_dir = workspace_dir
        self._ctx_dir = ctx_dir
        self._db_dsn = db_dsn
        self._history_all = history_all
        self._max_history_turns = max_history_turns
        self._sandbox_url = sandbox_url
        self._flags = flags or FeatureFlags()
        self._verbose = verbose

        self._step_callback = _make_step_callback(sender, routing_key)
        self._prune_keep_turns = 10
        self._session_loaded = False
        self._last_msgs: list[dict] = []
        self._history_len = 0
        self._turn_start_ts = int(time.time() * 1000)

        self._index_coroutine: Coroutine | None = None

    @agent
    def orchestrator(self) -> Agent:
        agents_cfg = yaml.safe_load(
            (_CONFIG_DIR / "agents.yaml").read_text(encoding="utf-8")
        )
        cfg = agents_cfg["orchestrator"]
        cfg["backstory"] = build_bootstrap_prompt(self._workspace_dir)

        from xiaopaw.tools.skill_loader import SkillLoaderTool

        skill_tool = SkillLoaderTool(
            session_id=self.session_id,
            sandbox_url=self._sandbox_url,
            routing_key=self.routing_key,
            history_all=self._history_all,
        )

        return Agent(
            **cfg,
            tools=[skill_tool, IntermediateTool()],
            llm=AliyunLLM(model="qwen3-max", region="cn", temperature=0.3),
            verbose=self._verbose,
        )

    @task
    def main_task(self) -> Task:
        tasks_cfg = yaml.safe_load(
            (_CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8")
        )
        return Task(
            **tasks_cfg["main_task"],
            agent=self.orchestrator(),
            output_pydantic=MainTaskOutput,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=self._verbose,
            step_callback=self._step_callback,
        )

    @before_llm_call
    def before_llm_hook(self, context: LLMCallHookContext) -> bool | None:
        if not self._session_loaded:
            self._restore_session(context)
            self._session_loaded = True
        self._last_msgs = context.messages
        prune_tool_results(context.messages, keep_turns=self._prune_keep_turns)
        maybe_compress(
            context.messages,
            model_limit=self._flags.context_window_tokens
            if hasattr(self._flags, "context_window_tokens")
            else 32000,
        )

        adapter = get_current_adapter()
        if adapter:
            adapter.on_before_llm(
                agent_role="orchestrator",
                messages=context.messages,
            )

        return None

    def _restore_session(self, context: LLMCallHookContext) -> None:
        history = load_session_ctx(self.session_id, ctx_dir=self._ctx_dir)
        if not history:
            return
        current_system_msgs = [m for m in context.messages if m.get("role") == "system"]
        current_user_msg = None
        for m in reversed(context.messages):
            if m.get("role") == "user":
                current_user_msg = m
                break

        hist_conv = [
            m for m in history
            if m.get("role") != "system"
            or "<context_summary>" in str(m.get("content", ""))
        ]

        self._history_len = len(current_system_msgs) + len(hist_conv)
        context.messages.clear()
        context.messages.extend(current_system_msgs)
        context.messages.extend(hist_conv)
        if current_user_msg:
            context.messages.append(current_user_msg)

    async def run_and_index(self) -> str:
        result = await self.crew().akickoff(
            inputs={
                "user_message": self.user_message,
                "history": _format_history(self._history_all, self._max_history_turns),
            }
        )

        new_msgs = self._last_msgs[self._history_len:] if self._last_msgs else []
        append_session_raw(self.session_id, new_msgs, self._ctx_dir)
        save_session_ctx(self.session_id, list(self._last_msgs), self._ctx_dir)

        try:
            reply = result.pydantic.reply if result.pydantic else result.raw
        except Exception:
            reply = str(result.raw) if result.raw else str(result)

        if self._db_dsn:
            self._index_coroutine = async_index_turn(
                session_id=self.session_id,
                routing_key=self.routing_key,
                user_message=self.user_message,
                assistant_reply=reply,
                turn_ts=self._turn_start_ts,
                db_dsn=self._db_dsn,
            )

        return reply


def build_agent_fn(
    sender: SenderProtocol,
    workspace_dir: Path,
    ctx_dir: Path,
    db_dsn: str = "",
    max_history_turns: int = _DEFAULT_MAX_HISTORY_TURNS,
    sandbox_url: str = "",
    flags: FeatureFlags | None = None,
) -> AgentFn:
    ctx_dir.mkdir(parents=True, exist_ok=True)

    async def agent_fn(
        user_message: str,
        history: list[MessageEntry],
        session_id: str,
        routing_key: str = "",
        verbose: bool = False,
    ) -> str:
        crew_instance = MemoryAwareCrew(
            session_id=session_id,
            routing_key=routing_key,
            user_message=user_message,
            sender=sender,
            workspace_dir=workspace_dir,
            ctx_dir=ctx_dir,
            history_all=history,
            db_dsn=db_dsn,
            max_history_turns=max_history_turns,
            sandbox_url=sandbox_url,
            flags=flags,
            verbose=verbose,
        )
        return await crew_instance.run_and_index()

    return agent_fn

"""SkillLoaderTool —— 渐进式能力披露 + Sub-Crew 触发器。

【课程对应】
- L17《项目实战 1：能力骨架》核心模式
- L29《零编排架构》：本工具的 _run() 触发 Sub-Crew 在子线程执行
- L33 机制二：本工具会显式捕获父 Langfuse span，让 Sub-Crew 的 trace 准确挂在 skill 调用之下

【渐进式能力披露的价值】
Main Crew 的 prompt 里**只放技能名+描述**（一两行），不放任何技能实现细节。
LLM 看到的"技能清单"始终保持小尺寸，避免被庞大的工具 schema 撑爆 context；
真正的实现复杂度推迟到 Sub-Crew 内部 ——
LLM 通过 skill_loader(skill_name="baidu_search", query=...) 调用，
本工具内部读取 SKILL.md → 构造 Sub-Crew → 在沙箱里执行 → 返回结果。

【两层 Crew 的责任划分】
- Main Crew  ：理解意图、选技能、维护对话上下文
- Sub-Crew   ：在沙箱里执行单一技能（路径隔离 + 工具受限）
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
from pathlib import Path

import yaml
from crewai.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr, field_validator

from xiaopaw.agents.skill_crew import build_skill_crew

logger = logging.getLogger(__name__)


def _get_langfuse_parent_span_id() -> str:
    """Capture current Langfuse parent span ID before Sub-Crew context copy."""
    try:
        from shared_hooks.langfuse_trace import _root_span_id_var, _span_stack_var

        stack = _span_stack_var.get(())
        if stack:
            return stack[-1][0]
        return _root_span_id_var.get("")
    except ImportError:
        return ""


def _reset_langfuse_contextvars(parent_span_id: str = "") -> None:
    """Reset Langfuse ContextVars for Sub-Crew isolation.

    Preserves _trace_id_var so sub-crew spans attach to the same trace.
    Sets _root_span_id_var to parent_span_id (skill_loader span) so
    sub-crew observations nest under it instead of being flat under
    the session root.
    Resets per-generation/tool counters to avoid state leakage.
    """
    try:
        from shared_hooks.langfuse_trace import (
            _closed_spans_var,
            _gen_count_var,
            _gen_id_var,
            _root_span_id_var,
            _span_stack_var,
            _tool_count_var,
        )

        if parent_span_id:
            _root_span_id_var.set(parent_span_id)
        else:
            stack = _span_stack_var.get(())
            if stack:
                _root_span_id_var.set(stack[-1][0])

        _gen_id_var.set("")
        _gen_count_var.set(0)
        _tool_count_var.set(0)
        _span_stack_var.set(())
        _closed_spans_var.set({})
    except ImportError:
        pass


def _flush_langfuse_subcrew() -> None:
    """Close remaining gen/spans and flush Langfuse buffer from sub-crew thread."""
    try:
        from shared_hooks.langfuse_trace import subcrew_cleanup
        subcrew_cleanup()
    except ImportError:
        pass

_SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
_SANDBOX_SKILLS_MOUNT = "/mnt/skills"
_CREWAI_VAR_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_\-]*)\}")


class SkillLoaderInput(BaseModel):
    skill_name: str = Field(..., description="Skill 名称，必须与可用列表中的 <name> 匹配")
    task_context: str = Field(
        default="",
        description="任务上下文，详细描述需要执行的操作。对于 task 类型的 Skill，建议使用 JSON 格式。",
    )

    @field_validator("task_context", mode="before")
    @classmethod
    def coerce(cls, v):
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)


class SkillLoaderTool(BaseTool):
    name: str = "skill_loader"
    description: str = ""
    args_schema: type = SkillLoaderInput

    _session_id: str = PrivateAttr(default="")
    _sandbox_url: str = PrivateAttr(default="")
    _routing_key: str = PrivateAttr(default="")
    _skill_registry: dict = PrivateAttr(default_factory=dict)
    _instruction_cache: dict = PrivateAttr(default_factory=dict)
    _history_all: list = PrivateAttr(default_factory=list)

    def __init__(
        self,
        session_id: str = "",
        sandbox_url: str = "",
        routing_key: str = "",
        history_all: list | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        if session_id and not _SESSION_ID_PATTERN.match(session_id):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        self._session_id = session_id
        self._sandbox_url = sandbox_url
        self._routing_key = routing_key
        self._history_all = history_all or []
        self._skill_registry = {}
        self._instruction_cache = {}
        self._build_description()

    def _build_description(self) -> None:
        manifest_path = _SKILLS_DIR / "load_skills.yaml"
        if not manifest_path.exists():
            self.description = "No skills available."
            return

        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        skills_xml: list[str] = []

        for skill_name, skill_cfg in manifest.items():
            if not skill_cfg.get("enabled", True):
                continue
            skill_path = skill_cfg.get("path", skill_name)
            if ".." in skill_path:
                logger.warning("path traversal blocked in skill: %s", skill_name)
                continue

            skill_dir = _SKILLS_DIR / skill_path
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            desc = self._extract_frontmatter_description(
                skill_md.read_text(encoding="utf-8")
            )
            skill_type = skill_cfg.get("type", "reference")

            self._skill_registry[skill_name] = {
                "type": skill_type,
                "path": skill_path,
                "dir": skill_dir,
            }

            skills_xml.append(
                f"  <skill>\n"
                f"    <name>{skill_name}</name>\n"
                f"    <type>{skill_type}</type>\n"
                f"    <description>{desc}</description>\n"
                f"  </skill>"
            )

        session_dir = f"/workspace/sessions/{self._session_id}" if self._session_id else "/workspace"
        header = (
            f"加载并调用 Skill。会话目录: {session_dir}\n"
            f"上传文件: {session_dir}/uploads/\n"
            f"输出文件: {session_dir}/outputs/\n\n"
            f"[重要] 下方 <name> 标签内容是 skill_name 参数值，不是工具名称。\n"
            f"正确调用方式：skill_loader(skill_name=\"baidu_search\", task_context=\"...\")\n"
            f"错误做法：直接以 baidu_search 为工具名调用（会报 Tool not found）\n\n"
        )
        self.description = (
            header
            + "<available_skills>\n"
            + "\n".join(skills_xml)
            + "\n</available_skills>"
        )

    def _extract_frontmatter_description(self, content: str) -> str:
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return content[:200]
        try:
            fm = yaml.safe_load(match.group(1))
            return str(fm.get("description", ""))[:200]
        except yaml.YAMLError:
            return content[:200]

    def _get_skill_instructions(self, skill_name: str) -> str:
        if skill_name in self._instruction_cache:
            return self._instruction_cache[skill_name]

        info = self._skill_registry[skill_name]
        skill_md = info["dir"] / "SKILL.md"
        raw = skill_md.read_text(encoding="utf-8")
        instructions = re.sub(r"^---\n.*?\n---\n?", "", raw, count=1, flags=re.DOTALL)

        session_dir = f"/workspace/sessions/{self._session_id}" if self._session_id else "/workspace"
        if self._sandbox_url:
            skill_base = f"{_SANDBOX_SKILLS_MOUNT}/{info['path']}"
        else:
            skill_base = str(info["dir"])
        instructions = instructions.replace("{skill_base}", skill_base)
        instructions = instructions.replace("{_skill_base}", skill_base)
        instructions = instructions.replace("{session_id}", self._session_id)
        instructions = instructions.replace("{session_dir}", session_dir)

        # Escape remaining braces to prevent CrewAI template errors
        def _escape_unresolved(text: str) -> str:
            return _CREWAI_VAR_PATTERN.sub(
                lambda m: "{{" + m.group(1) + "}}", text
            )

        instructions = _escape_unresolved(instructions)

        sandbox_directive = (
            f"\n\n<sandbox_execution_directive>\n"
            f"会话目录: {session_dir}\n"
            f"技能脚本目录: {skill_base}\n"
            f"routing_key: {self._routing_key}\n"
            f"执行脚本前请先 cd {skill_base}\n"
            f"</sandbox_execution_directive>"
        )
        instructions += sandbox_directive

        self._instruction_cache[skill_name] = instructions
        return instructions

    def _handle_history_reader(self, task_context: str) -> str:
        try:
            params = json.loads(task_context) if task_context else {}
        except json.JSONDecodeError:
            params = {}

        page = max(1, int(params.get("page", 1)))
        page_size = min(50, max(1, int(params.get("page_size", 20))))
        total = len(self._history_all)
        total_pages = max(1, (total + page_size - 1) // page_size)
        start = (page - 1) * page_size
        end = start + page_size
        messages = [
            {"role": m.role, "content": m.content, "ts": m.ts}
            for m in self._history_all[start:end]
        ]
        return json.dumps(
            {
                "errcode": 0,
                "message": "ok",
                "data": {
                    "messages": messages,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                },
            },
            ensure_ascii=False,
        )

    async def _execute_skill_async(
        self, skill_name: str, task_context: str
    ) -> str:
        if skill_name == "history_reader":
            return self._handle_history_reader(task_context)

        info = self._skill_registry[skill_name]
        instructions = self._get_skill_instructions(skill_name)

        if info["type"] == "reference":
            return f"<skill_instructions>\n{instructions}\n</skill_instructions>"

        crew = build_skill_crew(
            skill_name=skill_name,
            skill_instructions=instructions,
            session_id=self._session_id,
            sandbox_mcp_url=self._sandbox_url,
        )

        inputs = {"task_context": task_context, "skill_name": skill_name}
        for m in _CREWAI_VAR_PATTERN.finditer(instructions):
            var = m.group(1)
            if var not in inputs:
                inputs[var] = var

        try:
            result = await crew.akickoff(inputs=inputs)
            return str(result)
        finally:
            hook = getattr(crew, "_subcrew_tool_hook", None)
            if hook is not None:
                try:
                    from crewai.hooks import unregister_before_tool_call_hook
                    unregister_before_tool_call_hook(hook)
                except (ValueError, AttributeError):
                    pass
            for agent in crew.agents:
                for mcp in getattr(agent, "mcps", []) or []:
                    try:
                        if hasattr(mcp, "stop") and callable(mcp.stop):
                            await asyncio.wait_for(mcp.stop(), timeout=10.0)
                    except asyncio.TimeoutError:
                        logger.warning(
                            "MCP graceful stop timed out after 10s for %s, "
                            "deferring to event loop cleanup",
                            skill_name,
                        )
                    except Exception as exc:
                        logger.warning("MCP cleanup error (non-fatal): %s", exc)

    async def _arun(self, skill_name: str, task_context: str = "") -> str:
        if skill_name not in self._skill_registry and skill_name != "history_reader":
            available = ", ".join(sorted(self._skill_registry.keys()))
            return (
                f"错误：未找到 Skill '{skill_name}'。\n"
                f"可用 Skills: {available}"
            )
        return await self._execute_skill_async(skill_name, task_context)

    def _run(self, skill_name: str, task_context: str = "") -> str:
        if skill_name not in self._skill_registry and skill_name != "history_reader":
            available = ", ".join(sorted(self._skill_registry.keys()))
            return (
                f"错误：未找到 Skill '{skill_name}'。\n"
                f"可用 Skills: {available}"
            )

        import contextvars

        parent_span_id = _get_langfuse_parent_span_id()
        ctx = contextvars.copy_context()

        def _run_with_cleanup():
            loop = asyncio.new_event_loop()
            _reset_langfuse_contextvars(parent_span_id)
            try:
                return loop.run_until_complete(
                    self._execute_skill_async(skill_name, task_context)
                )
            finally:
                _flush_langfuse_subcrew()
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                if pending:
                    try:
                        loop.run_until_complete(
                            asyncio.wait_for(
                                asyncio.gather(*pending, return_exceptions=True),
                                timeout=15.0,
                            )
                        )
                    except (asyncio.TimeoutError, Exception):
                        logger.warning("Event loop cleanup timed out, forcing close")
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(ctx.run, _run_with_cleanup)
            return future.result(timeout=300)

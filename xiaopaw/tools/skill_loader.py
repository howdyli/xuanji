"""SkillLoaderTool: progressive disclosure skill catalog + Sub-Crew trigger."""

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
            f"routing_key: {self._routing_key}\n"
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

        result = await crew.akickoff(inputs=inputs)
        return str(result)

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

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                self._execute_skill_async(skill_name, task_context),
            )
            return future.result()

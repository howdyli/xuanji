"""Sub-Crew factory for Skill execution in AIO-Sandbox."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task
from crewai.mcp import MCPServerHTTP

from xiaopaw.llm.aliyun_llm import AliyunLLM

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent / "config"
_DEFAULT_SANDBOX_MCP_URL = "http://localhost:8022/mcp"


def _format_cfg(cfg: dict, **kwargs) -> dict:
    result = {}
    for k, v in cfg.items():
        if isinstance(v, str):
            result[k] = v.format(**kwargs)
        else:
            result[k] = v
    return result


def build_skill_crew(
    skill_name: str,
    skill_instructions: str,
    session_id: str = "",
    sandbox_mcp_url: str = _DEFAULT_SANDBOX_MCP_URL,
    sub_agent_model: str = "qwen3-max",
    max_iter: int = 20,
    allowed_tools: list[str] | None = None,
) -> Crew:
    sandbox_mcp = MCPServerHTTP(url=sandbox_mcp_url)
    skill_llm = AliyunLLM(model=sub_agent_model, region="cn", temperature=0.3)

    session_dir = f"/workspace/sessions/{session_id}" if session_id else "/workspace"

    agents_cfg = yaml.safe_load((_CONFIG_DIR / "agents.yaml").read_text(encoding="utf-8"))
    tasks_cfg = yaml.safe_load((_CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8"))

    agent_cfg = _format_cfg(
        agents_cfg["skill_agent"],
        skill_name=skill_name,
        skill_name_upper=skill_name.upper(),
        session_dir=session_dir,
        skill_instructions=skill_instructions,
    )
    agent_cfg["max_iter"] = max_iter

    skill_agent = Agent(
        **agent_cfg,
        llm=skill_llm,
        mcps=[sandbox_mcp],
        verbose=True,
    )

    task_cfg = _format_cfg(tasks_cfg["skill_task"], session_dir=session_dir)
    skill_task = Task(**task_cfg, agent=skill_agent)

    return Crew(
        agents=[skill_agent],
        tasks=[skill_task],
        process=Process.sequential,
        verbose=True,
    )

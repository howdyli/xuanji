"""main_crew 远程记忆召回注入（Phase 3 PRD AC-1/AC-2）单元测试。

验证 orchestrator backstory 的 <long_term_memory> 注入行为：
- 有召回内容 → 注入段位于 bootstrap prompt 之后；
- 空召回 → backstory 与不启用时逐字节一致（零污染）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import xiaopaw.agents.main_crew as main_crew_mod
from xiaopaw.agents.main_crew import MemoryAwareCrew
from xiaopaw.llm.aliyun_llm import AliyunLLM
from xiaopaw.memory.bootstrap import build_bootstrap_prompt


@pytest.fixture(autouse=True)
def _offline_router(monkeypatch):
    """orchestrator 构造依赖 model_router；离线 LLM 避免读环境/网络。"""
    monkeypatch.setattr(
        main_crew_mod.model_router,
        "get_llm",
        lambda task_type=None: AliyunLLM(
            model="deepseek-chat", region="deepseek", api_key="test-key"
        ),
    )


def _make_crew(
    tmp_path, recalled_memory: str = "", user_preferences: dict | None = None
) -> MemoryAwareCrew:
    return MemoryAwareCrew(
        session_id="s1",
        routing_key="p2p:web_u",
        user_message="hi",
        sender=MagicMock(),
        workspace_dir=tmp_path,
        ctx_dir=tmp_path / "ctx",
        history_all=[],
        recalled_memory=recalled_memory,
        user_preferences=user_preferences,
    )


def test_backstory_injects_recalled_memory_after_bootstrap(tmp_path):
    recalled = "用户偏好：喜欢喝美式咖啡"
    agent = _make_crew(tmp_path, recalled_memory=recalled).orchestrator()
    bootstrap = build_bootstrap_prompt(tmp_path)

    assert agent.backstory.startswith(bootstrap)
    injected = agent.backstory[len(bootstrap):]
    assert "<long_term_memory>" in injected
    assert recalled in injected
    assert injected.rstrip().endswith("</long_term_memory>")


def test_backstory_unchanged_when_recall_empty(tmp_path):
    agent = _make_crew(tmp_path, recalled_memory="").orchestrator()

    # 空召回零污染：backstory 与 bootstrap prompt 逐字节一致
    assert agent.backstory == build_bootstrap_prompt(tmp_path)
    assert "<long_term_memory>" not in agent.backstory


# Phase 4 FR-1：<user_preferences> 段注入


def test_backstory_injects_user_preferences(tmp_path):
    prefs = {"reply_language": "英文", "coffee_preference": "美式咖啡"}
    agent = _make_crew(tmp_path, user_preferences=prefs).orchestrator()

    assert "<user_preferences>" in agent.backstory
    assert "- reply_language: 英文" in agent.backstory
    assert "- coffee_preference: 美式咖啡" in agent.backstory


def test_backstory_no_preferences_section_when_empty(tmp_path):
    agent = _make_crew(tmp_path, user_preferences={}).orchestrator()
    assert "<user_preferences>" not in agent.backstory


def test_preferences_injected_after_recall_section(tmp_path):
    agent = _make_crew(
        tmp_path, recalled_memory="召回内容", user_preferences={"k": "v"}
    ).orchestrator()
    assert agent.backstory.index("<long_term_memory>") < agent.backstory.index(
        "<user_preferences>"
    )

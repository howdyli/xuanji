"""Unit tests for SkillLoaderTool instruction caching.

Regression guard for a cross-session cache leak: the skill instruction cache is
a process-wide singleton, and the rendered instructions embed session-scoped
values (session dir, routing_key, sandbox mount). Keying the cache on
``skill_name`` alone would return one session's paths to another session.
See xiaopaw/tools/skill_loader.py::_instruction_cache_key.
"""

from __future__ import annotations

from xiaopaw.tools.skill_loader import SkillLoaderTool


def _make_tool(session_id: str, routing_key: str, sandbox_url: str = "") -> SkillLoaderTool:
    return SkillLoaderTool(
        session_id=session_id,
        routing_key=routing_key,
        sandbox_url=sandbox_url,
    )


def test_cache_key_differs_across_sessions():
    a = _make_tool("session_a", "rk_a")
    b = _make_tool("session_b", "rk_b")
    assert a._instruction_cache_key("pdf") != b._instruction_cache_key("pdf")


def test_cache_key_differs_by_routing_key():
    a = _make_tool("session_shared", "rk_a")
    b = _make_tool("session_shared", "rk_b")
    assert a._instruction_cache_key("pdf") != b._instruction_cache_key("pdf")


def test_cache_key_differs_by_sandbox():
    local = _make_tool("session_x", "rk_x", sandbox_url="")
    sandboxed = _make_tool("session_x", "rk_x", sandbox_url="http://sandbox:8080")
    assert local._instruction_cache_key("pdf") != sandboxed._instruction_cache_key("pdf")


def test_cache_key_stable_for_same_inputs():
    a = _make_tool("session_x", "rk_x")
    b = _make_tool("session_x", "rk_x")
    assert a._instruction_cache_key("pdf") == b._instruction_cache_key("pdf")
    # Different skills within the same session must still differ.
    assert a._instruction_cache_key("pdf") != a._instruction_cache_key("baidu_search")

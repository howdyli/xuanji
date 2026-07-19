"""Unit tests for the agents layer: main_crew helpers, skill_crew helpers, models.

All tests are based on real code. CrewAI runtime (LLM/Agent/Crew) is NOT required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════════════
# main_crew.py — pure helper functions
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.agents.main_crew import (
    _is_mcp_sandbox_tool,
    _normalize_tool_input,
    _MCP_TOOL_PREFIXES,
)


class TestIsMcpSandboxTool:
    """_is_mcp_sandbox_tool: 判断工具名是否为 MCP/sandbox 前缀。"""

    def test_sandbox_prefix(self):
        assert _is_mcp_sandbox_tool("sandbox_execute") is True

    def test_mcp_prefix(self):
        assert _is_mcp_sandbox_tool("mcp_read_file") is True

    def test_no_prefix(self):
        assert _is_mcp_sandbox_tool("read_file") is False

    def test_partial_prefix_no_match(self):
        """前缀必须完整匹配，'san' 不是 'sandbox_'。"""
        assert _is_mcp_sandbox_tool("san_tool") is False

    def test_empty_string(self):
        assert _is_mcp_sandbox_tool("") is False

    def test_prefixes_tuple_not_empty(self):
        assert len(_MCP_TOOL_PREFIXES) >= 2


class TestNormalizeToolInput:
    """_normalize_tool_input: MCP sandbox 工具参数 Python 风格值归一化。"""

    def test_none_string_removed(self):
        d = {"key": "None", "other": "value"}
        _normalize_tool_input(d)
        assert "key" not in d
        assert d["other"] == "value"

    def test_true_string_converted(self):
        d = {"flag": "True"}
        _normalize_tool_input(d)
        assert d["flag"] is True

    def test_false_string_converted(self):
        d = {"flag": "False"}
        _normalize_tool_input(d)
        assert d["flag"] is False

    def test_non_string_values_untouched(self):
        d = {"count": 42, "nested": {"a": 1}}
        _normalize_tool_input(d)
        assert d["count"] == 42
        assert d["nested"] == {"a": 1}

    def test_regular_string_untouched(self):
        d = {"name": "hello world"}
        _normalize_tool_input(d)
        assert d["name"] == "hello world"

    def test_empty_dict(self):
        d = {}
        _normalize_tool_input(d)
        assert d == {}

    def test_multiple_none_values(self):
        d = {"a": "None", "b": "None", "c": "keep"}
        _normalize_tool_input(d)
        assert "a" not in d
        assert "b" not in d
        assert d["c"] == "keep"


# ═══════════════════════════════════════════════════════════════════════════
# skill_crew.py — helper functions
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.agents.skill_crew import (
    _normalize_subcrew_tool_input,
    _format_cfg,
    _STRING_CONTENT_FIELDS,
    build_skill_crew,
)


class TestNormalizeSubcrewToolInput:
    """_normalize_subcrew_tool_input: dict/list 值转 JSON 字符串。"""

    def test_dict_value_to_json(self):
        d = {"content": {"key": "val"}}
        _normalize_subcrew_tool_input(d)
        assert d["content"] == '{"key": "val"}'

    def test_list_value_to_json(self):
        d = {"file_text": [1, 2, 3]}
        _normalize_subcrew_tool_input(d)
        assert d["file_text"] == "[1, 2, 3]"

    def test_string_value_untouched(self):
        d = {"content": "plain text"}
        _normalize_subcrew_tool_input(d)
        assert d["content"] == "plain text"

    def test_non_target_field_untouched(self):
        d = {"filename": {"nested": True}}
        _normalize_subcrew_tool_input(d)
        assert d["filename"] == {"nested": True}

    def test_new_str_field(self):
        d = {"new_str": {"data": 1}}
        _normalize_subcrew_tool_input(d)
        assert d["new_str"] == '{"data": 1}'

    def test_empty_dict(self):
        d = {}
        _normalize_subcrew_tool_input(d)
        assert d == {}

    def test_content_fields_set(self):
        """_STRING_CONTENT_FIELDS 包含预期的字段名。"""
        assert "content" in _STRING_CONTENT_FIELDS
        assert "file_text" in _STRING_CONTENT_FIELDS
        assert "new_str" in _STRING_CONTENT_FIELDS


class TestFormatCfg:
    """_format_cfg: 对 config dict 中字符串值做 .format() 替换。"""

    def test_basic_substitution(self):
        cfg = {"name": "skill_{skill_name}", "count": 3}
        result = _format_cfg(cfg, skill_name="pdf")
        assert result["name"] == "skill_pdf"
        assert result["count"] == 3

    def test_multiple_placeholders(self):
        cfg = {"desc": "{a} and {b}"}
        result = _format_cfg(cfg, a="X", b="Y")
        assert result["desc"] == "X and Y"

    def test_non_string_values_passthrough(self):
        cfg = {"items": [1, 2], "flag": True, "count": 42}
        result = _format_cfg(cfg)
        assert result["items"] == [1, 2]
        assert result["flag"] is True
        assert result["count"] == 42

    def test_empty_cfg(self):
        assert _format_cfg({}) == {}


class TestBuildSkillCrewValidation:
    """build_skill_crew: URL 校验（不需要真实 CrewAI 运行时）。"""

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="sandbox_mcp_url must be an http"):
            build_skill_crew(
                skill_name="test",
                skill_instructions="do stuff",
                sandbox_mcp_url="",
            )

    def test_non_http_url_raises(self):
        with pytest.raises(ValueError, match="sandbox_mcp_url must be an http"):
            build_skill_crew(
                skill_name="test",
                skill_instructions="do stuff",
                sandbox_mcp_url="ftp://bad.url",
            )

    def test_none_url_raises(self):
        with pytest.raises(ValueError):
            build_skill_crew(
                skill_name="test",
                skill_instructions="do stuff",
                sandbox_mcp_url=None,
            )


# ═══════════════════════════════════════════════════════════════════════════
# models.py — Pydantic output model
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.agents.models import MainTaskOutput


class TestMainTaskOutput:
    """MainTaskOutput: Pydantic 输出模型验证。"""

    def test_basic_creation(self):
        out = MainTaskOutput(reply="你好")
        assert out.reply == "你好"
        assert out.used_skills == []

    def test_with_skills(self):
        out = MainTaskOutput(reply="done", used_skills=["pdf", "search"])
        assert len(out.used_skills) == 2
        assert "pdf" in out.used_skills

    def test_reply_required(self):
        with pytest.raises(Exception):
            MainTaskOutput()  # reply is required (no default)

    def test_serialization(self):
        out = MainTaskOutput(reply="test", used_skills=["a"])
        d = out.model_dump()
        assert d["reply"] == "test"
        assert d["used_skills"] == ["a"]


# ═══════════════════════════════════════════════════════════════════════════
# main_crew.py — step callback (mock CrewAI adapter)
# ═══════════════════════════════════════════════════════════════════════════


class TestMakeStepCallback:
    """_make_step_callback: hook 框架集成回调。"""

    @pytest.mark.asyncio
    async def test_callback_no_adapter_does_nothing(self):
        """adapter 为 None 时回调不报错。"""
        from xiaopaw.agents.main_crew import _make_step_callback

        sender = MagicMock()
        cb = _make_step_callback(sender, "rk")
        with patch("xiaopaw.agents.main_crew.get_current_adapter", return_value=None):
            await cb(MagicMock())  # should not raise

    @pytest.mark.asyncio
    async def test_callback_dispatches_after_turn(self):
        """adapter 存在时调用 dispatch_after_turn。"""
        from xiaopaw.agents.main_crew import _make_step_callback
        from crewai.agents.parser import AgentAction

        sender = MagicMock()
        cb = _make_step_callback(sender, "rk")
        adapter = MagicMock()
        adapter._pending_deny = None

        action = MagicMock(spec=AgentAction)
        action.text = "some output"
        action.thought = ""

        with patch("xiaopaw.agents.main_crew.get_current_adapter", return_value=adapter):
            await cb(action)

        adapter.dispatch_after_turn.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_re_raises_pending_deny(self):
        """pending_deny 存在时回调重抛异常。"""
        from xiaopaw.agents.main_crew import _make_step_callback
        from crewai.agents.parser import AgentFinish

        sender = MagicMock()
        cb = _make_step_callback(sender, "rk")
        adapter = MagicMock()
        deny_exc = RuntimeError("GuardrailDeny: blocked")
        adapter._pending_deny = deny_exc

        finish = MagicMock(spec=AgentFinish)
        finish.output = "done"

        with patch("xiaopaw.agents.main_crew.get_current_adapter", return_value=adapter):
            with pytest.raises(RuntimeError, match="GuardrailDeny"):
                await cb(finish)

        # pending_deny should be cleared
        assert adapter._pending_deny is None


# ═══════════════════════════════════════════════════════════════════════════
# main_crew.py — _make_step_callback (sub-crew variant)
# ═══════════════════════════════════════════════════════════════════════════


class TestMakeSubcrewStepCallback:
    """_make_subcrew_step_callback: sub-crew 变体回调。"""

    @pytest.mark.asyncio
    async def test_subcrew_callback_no_adapter(self):
        from xiaopaw.agents.skill_crew import _make_subcrew_step_callback

        with patch("xiaopaw.hook_framework.crew_adapter.get_current_adapter", return_value=None):
            cb = _make_subcrew_step_callback()
            await cb(MagicMock())  # should not raise

    @pytest.mark.asyncio
    async def test_subcrew_callback_dispatches_after_turn(self):
        from xiaopaw.agents.skill_crew import _make_subcrew_step_callback
        from crewai.agents.parser import AgentAction

        adapter = MagicMock()
        adapter._pending_deny = None

        action = MagicMock(spec=AgentAction)
        action.text = "sub output"
        action.thought = ""

        with patch("xiaopaw.hook_framework.crew_adapter.get_current_adapter", return_value=adapter):
            cb = _make_subcrew_step_callback()
            await cb(action)

        adapter.dispatch_after_turn.assert_called_once()

"""Phase 4 FR-1/FR-2 单元测试：偏好保存工具 + memory.md 迁移脚本。"""

from __future__ import annotations

from unittest.mock import patch

from xiaopaw.tools.save_preference_tool import SaveUserPreferenceTool

from scripts.migrate_memory_md import entry_key, parse_preferences


class TestSaveUserPreferenceTool:
    def test_invalid_key_rejected(self):
        tool = SaveUserPreferenceTool()
        assert "不符合" in tool._run(key="Reply Language!", value="英文")

    def test_empty_value_rejected(self):
        tool = SaveUserPreferenceTool()
        assert "value 不能为空" in tool._run(key="reply_language", value="  ")

    def test_disabled_store_hint(self):
        tool = SaveUserPreferenceTool()
        with patch(
            "xiaopaw.tools.save_preference_tool.remote_memory_store"
        ) as store:
            store.is_enabled = False
            assert "未启用" in tool._run(key="reply_language", value="英文")

    def test_success_path(self):
        tool = SaveUserPreferenceTool()
        with patch(
            "xiaopaw.tools.save_preference_tool.remote_memory_store"
        ) as store:
            store.is_enabled = True
            store.set_preference_sync.return_value = True
            result = tool._run(key="Reply_Language", value=" 英文 ")
            # key 归一化为小写、value 去空白
            store.set_preference_sync.assert_called_once_with("reply_language", "英文")
            assert "已保存" in result

    def test_write_failure_degrades(self):
        tool = SaveUserPreferenceTool()
        with patch(
            "xiaopaw.tools.save_preference_tool.remote_memory_store"
        ) as store:
            store.is_enabled = True
            store.set_preference_sync.return_value = False
            assert "失败" in tool._run(key="reply_language", value="英文")


_MEMORY_MD = """# 长期记忆索引

## 用户重要事项

> （XiaoPaw 运行后自动写入：用户提及的关键事项、偏好、项目状态等）

- 用户偏好中文回复
- 用户是后端工程师
* 喜欢喝美式咖啡

## 待跟进事项

- 这条属于待办，不应被迁移

## 近期对话摘要

- 这条属于摘要，不应被迁移
"""


class TestMigrateMemoryMd:
    def test_parse_only_preference_section(self):
        entries = parse_preferences(_MEMORY_MD)
        assert entries == ["用户偏好中文回复", "用户是后端工程师", "喜欢喝美式咖啡"]

    def test_template_comments_skipped(self):
        assert all("自动写入" not in e for e in parse_preferences(_MEMORY_MD))

    def test_empty_template_yields_nothing(self):
        template = "# 长期记忆索引\n\n## 用户重要事项\n\n> 模板注释\n"
        assert parse_preferences(template) == []

    def test_entry_key_stable_for_idempotency(self):
        # 同一条目重复执行生成同一 key → upsert 覆盖，幂等
        assert entry_key("用户偏好中文回复") == entry_key("用户偏好中文回复")
        assert entry_key("a") != entry_key("b")
        assert entry_key("x").startswith("mem_md_")

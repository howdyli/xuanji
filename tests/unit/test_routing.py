"""Unit tests for the routing layer: listener, sender, session, cron, context_builder.

All tests based on real code. No external services (Feishu, WebSocket, LLM) required.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ═══════════════════════════════════════════════════════════════════════════
# feishu/session_key.py — routing key resolution
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.feishu.session_key import resolve_routing_key, routing_type


class TestResolveRoutingKey:
    def test_p2p_no_thread(self):
        assert resolve_routing_key("p2p", "chat1", "user1") == "p2p:user1"

    def test_group_no_thread(self):
        assert resolve_routing_key("group", "chat1", "user1") == "group:chat1"

    def test_thread_takes_priority(self):
        result = resolve_routing_key("group", "chat1", "user1", thread_id="th1")
        assert result == "thread:chat1:th1"

    def test_p2p_with_thread(self):
        result = resolve_routing_key("p2p", "chat1", "user1", thread_id="th1")
        assert result == "thread:chat1:th1"

    def test_empty_thread_falls_through(self):
        assert resolve_routing_key("p2p", "c", "u", thread_id="") == "p2p:u"


class TestRoutingType:
    def test_p2p(self):
        assert routing_type("p2p:user1") == "p2p"

    def test_group(self):
        assert routing_type("group:chat1") == "group"

    def test_thread(self):
        assert routing_type("thread:chat1:th1") == "thread"

    def test_no_colon(self):
        assert routing_type("unknown") == "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# feishu/sender.py — card building and routing key parsing
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.feishu.sender import FeishuSender


class TestFeishuSenderHelpers:
    def test_parse_routing_key_p2p(self):
        chat_type, chat_id = FeishuSender._parse_routing_key("p2p:user_open_id")
        assert chat_type == "p2p"
        assert chat_id == "user_open_id"

    def test_parse_routing_key_group(self):
        chat_type, chat_id = FeishuSender._parse_routing_key("group:oc_xxx")
        assert chat_type == "group"
        assert chat_id == "oc_xxx"

    def test_parse_routing_key_no_colon(self):
        chat_type, chat_id = FeishuSender._parse_routing_key("just_id")
        assert chat_type == "p2p"
        assert chat_id == "just_id"

    def test_parse_routing_key_thread(self):
        chat_type, chat_id = FeishuSender._parse_routing_key("thread:oc_xxx:th_yyy")
        assert chat_type == "thread"
        assert chat_id == "oc_xxx:th_yyy"

    def test_build_card_structure(self):
        sender = FeishuSender(client=MagicMock())
        card_json = sender._build_card("Hello world")
        card = json.loads(card_json)
        assert card["config"]["wide_screen_mode"] is True
        assert len(card["elements"]) == 1
        assert card["elements"][0]["tag"] == "div"
        assert card["elements"][0]["text"]["content"] == "Hello world"
        assert card["elements"][0]["text"]["tag"] == "lark_md"

    def test_build_card_chinese_content(self):
        sender = FeishuSender(client=MagicMock())
        card_json = sender._build_card("你好世界")
        card = json.loads(card_json)
        assert card["elements"][0]["text"]["content"] == "你好世界"


# ═══════════════════════════════════════════════════════════════════════════
# session/models.py — session ID generation
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.session.models import (
    _new_session_id,
    _new_dated_session_id,
    MessageEntry,
    SessionEntry,
    RoutingEntry,
)


class TestSessionIdGeneration:
    def test_new_session_id_format(self):
        sid = _new_session_id()
        assert sid.startswith("s-")
        assert len(sid) == 14  # s- + 12 hex chars

    def test_dated_session_id_format(self):
        sid = _new_dated_session_id(set())
        assert sid.startswith("s-")
        parts = sid.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD
        assert parts[2] == "001"

    def test_dated_session_id_sequencing(self):
        existing = {"s-20260708-001", "s-20260708-002"}
        from datetime import date
        today_prefix = f"s-{date.today().strftime('%Y%m%d')}-"
        # Existing IDs won't match today unless today is 20260708
        sid = _new_dated_session_id(existing)
        assert sid.startswith("s-")

    def test_dated_session_id_with_existing_today(self):
        from datetime import date
        today = date.today().strftime("%Y%m%d")
        existing = {f"s-{today}-001", f"s-{today}-003"}
        sid = _new_dated_session_id(existing)
        assert sid == f"s-{today}-004"

    def test_dated_session_id_ignores_other_dates(self):
        from datetime import date
        today = date.today().strftime("%Y%m%d")
        existing = {"s-20200101-999", "s-20200101-001"}
        sid = _new_dated_session_id(existing)
        assert sid == f"s-{today}-001"


class TestSessionModels:
    def test_message_entry_fields(self):
        m = MessageEntry(role="user", content="hello", ts=1000)
        assert m.role == "user"
        assert m.feishu_msg_id is None

    def test_session_entry_defaults(self):
        s = SessionEntry()
        assert s.title == ""
        assert s.verbose is False
        assert s.message_count == 0

    def test_routing_entry(self):
        r = RoutingEntry(active_session_id="s-1", sessions=[SessionEntry(id="s-1")])
        assert r.active_session_id == "s-1"
        assert len(r.sessions) == 1


# ═══════════════════════════════════════════════════════════════════════════
# session/manager.py — LRU lock cache
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.session.manager import _LRULockCache


class TestLRULockCache:
    def test_get_creates_lock(self):
        cache = _LRULockCache(maxsize=3)
        lock = cache.get("a")
        assert lock is not None

    def test_get_returns_same_lock(self):
        cache = _LRULockCache(maxsize=3)
        lock1 = cache.get("a")
        lock2 = cache.get("a")
        assert lock1 is lock2

    def test_eviction_at_maxsize(self):
        cache = _LRULockCache(maxsize=2)
        lock_a = cache.get("a")
        cache.get("b")
        # Adding "c" should evict "a" (oldest)
        cache.get("c")
        new_a = cache.get("a")
        assert new_a is not lock_a  # evicted and recreated

    def test_access_refreshes_position(self):
        cache = _LRULockCache(maxsize=2)
        cache.get("a")
        lock_b = cache.get("b")
        # Access "a" again → "b" becomes oldest
        cache.get("a")
        cache.get("c")
        # "b" should be evicted, not "a"
        assert cache.get("b") is not lock_b


# ═══════════════════════════════════════════════════════════════════════════
# session/context_builder.py — context building
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.session.context_builder import (
    ContextBuilder,
    ToolCallSummary,
    extract_tool_summaries,
    format_message_line,
    _escape_attr,
)


class TestEscapeAttr:
    def test_ampersand(self):
        assert "&amp;" in _escape_attr("a&b")

    def test_quotes(self):
        assert "&quot;" in _escape_attr('a"b')

    def test_angle_brackets(self):
        assert "&lt;" in _escape_attr("a<b")
        assert "&gt;" in _escape_attr("a>b")

    def test_no_escape_needed(self):
        assert _escape_attr("hello") == "hello"


class TestToolCallSummary:
    def test_format_basic(self):
        s = ToolCallSummary(tool_name="search", key_param="query")
        assert s.format() == "[tool: search: query]"

    def test_format_truncated(self):
        s = ToolCallSummary(tool_name="read", key_param="x" * 100, truncated=True)
        result = s.format()
        assert result.endswith("...]")
        assert len(result) < 120

    def test_format_empty_param(self):
        s = ToolCallSummary(tool_name="list", key_param="")
        assert s.format() == "[tool: list: ]"


class TestExtractToolSummaries:
    def test_tool_pattern(self):
        summaries = extract_tool_summaries("[Tool: search] did something")
        assert len(summaries) >= 1
        assert summaries[0].tool_name == "search"

    def test_skill_pattern(self):
        summaries = extract_tool_summaries("使用技能: pdf_tool 来生成")
        assert any(s.tool_name == "skill" for s in summaries)

    def test_no_patterns(self):
        summaries = extract_tool_summaries("just plain text")
        assert summaries == []


class TestFormatMessageLine:
    def test_user_message(self):
        msg = MessageEntry(role="user", content="Hello", ts=1000)
        line = format_message_line(msg)
        assert line == "[user]: Hello"

    def test_empty_content_returns_none(self):
        msg = MessageEntry(role="user", content="   ", ts=1000)
        assert format_message_line(msg) is None

    def test_long_content_truncated(self):
        msg = MessageEntry(role="user", content="x" * 600, ts=1000)
        line = format_message_line(msg)
        assert "...[truncated]" in line


class TestContextBuilder:
    def test_empty_history_returns_user_message(self):
        builder = ContextBuilder()
        result = builder.build_context_from_history([], "hello")
        assert result == "hello"

    def test_with_history_wraps_in_tags(self):
        builder = ContextBuilder()
        history = [
            MessageEntry(role="user", content="Hi", ts=1000),
            MessageEntry(role="assistant", content="Hello!", ts=2000),
        ]
        result = builder.build_context_from_history(history, "new msg", session_id="s-1")
        assert "<conversation_history>" in result
        assert "new msg" in result
        assert "Session ID: s-1" in result

    def test_respects_max_context_chars(self):
        builder = ContextBuilder(max_context_chars=50)
        history = [MessageEntry(role="user", content="x" * 200, ts=i) for i in range(10)]
        result = builder.build_context_from_history(history, "q")
        # Should stop early due to char budget
        assert len(result) < 500

    def test_recovery_prompt_structure(self):
        builder = ContextBuilder()
        result = builder.build_recovery_prompt("s-test", "continue work", title="My Session")
        assert "<session_recovery>" in result
        assert "s-test" in result
        assert "My Session" in result
        assert "continue work" in result

    def test_cross_session_ref(self):
        builder = ContextBuilder()
        refs = [
            {"id": "s-other", "title": "Other Session", "updated_at": "2026-07-08"},
        ]
        result = builder.build_cross_session_ref("s-current", refs)
        assert "<referenced_sessions>" in result
        assert "s-other" in result

    def test_cross_session_ref_skips_self(self):
        builder = ContextBuilder()
        refs = [{"id": "s-current", "title": "Self"}]
        result = builder.build_cross_session_ref("s-current", refs)
        assert result == ""


# ═══════════════════════════════════════════════════════════════════════════
# cron/models.py — CronJob model
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.cron.models import CronJob


class TestCronJob:
    def test_basic_creation(self):
        job = CronJob(id="j1", cron_expr="* * * * *", content="hello")
        assert job.enabled is True
        assert job.fail_count == 0
        assert job.max_retries == 3

    def test_skill_action_type(self):
        job = CronJob(id="j2", cron_expr="0 * * * *", content="x",
                       action_type="skill", skill_name="search")
        assert job.action_type == "skill"
        assert job.skill_name == "search"

    def test_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            CronJob(id="j3", cron_expr="*", content="x", unknown_field="bad")


# ═══════════════════════════════════════════════════════════════════════════
# cron/service.py — content building
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.cron.service import CronService


class TestCronServiceBuildContent:
    def _make_service(self):
        return CronService(
            storage=MagicMock(),
            dispatch_fn=AsyncMock(),
            check_interval=60.0,
        )

    def test_dispatch_content_with_name(self):
        svc = self._make_service()
        job = CronJob(id="j1", cron_expr="* * * * *", content="do stuff",
                       name="My Task", action_type="dispatch")
        result = svc._build_content(job)
        assert "[Auto Task: My Task]" in result
        assert "do stuff" in result

    def test_skill_content(self):
        svc = self._make_service()
        job = CronJob(id="j2", cron_expr="* * * * *", content="search news",
                       name="Search", action_type="skill", skill_name="baidu_search")
        result = svc._build_content(job)
        assert "请使用技能：baidu_search" in result
        assert "search news" in result

    def test_content_without_name(self):
        svc = self._make_service()
        job = CronJob(id="j3", cron_expr="* * * * *", content="raw content")
        result = svc._build_content(job)
        assert result == "raw content"


# ═══════════════════════════════════════════════════════════════════════════
# cron/storage.py — SQLite CRUD (uses real temp SQLite)
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.cron.storage import CronStorage


class TestCronStorage:
    @pytest.fixture
    def storage(self, tmp_path):
        return CronStorage(db_path=tmp_path / "test.db")

    def test_create_and_get(self, storage):
        result = storage.create({"name": "test", "cron_expr": "* * * * *", "content": "hello"})
        assert result["name"] == "test"
        assert result["enabled"] is True
        fetched = storage.get(result["id"])
        assert fetched is not None
        assert fetched["name"] == "test"

    def test_load_all(self, storage):
        storage.create({"name": "a", "cron_expr": "0 * * * *", "content": "a"})
        storage.create({"name": "b", "cron_expr": "0 * * * *", "content": "b"})
        jobs = storage.load_all()
        assert len(jobs) == 2

    def test_update(self, storage):
        result = storage.create({"name": "orig", "cron_expr": "* * * * *", "content": "x"})
        updated = storage.update(result["id"], {"name": "updated"})
        assert updated["name"] == "updated"

    def test_update_nonexistent(self, storage):
        assert storage.update("nonexistent", {"name": "x"}) is None

    def test_delete(self, storage):
        result = storage.create({"name": "del", "cron_expr": "*", "content": "x"})
        assert storage.delete(result["id"]) is True
        assert storage.get(result["id"]) is None

    def test_delete_nonexistent(self, storage):
        assert storage.delete("nope") is False

    def test_toggle(self, storage):
        result = storage.create({"name": "tog", "cron_expr": "*", "content": "x"})
        assert result["enabled"] is True
        toggled = storage.toggle(result["id"])
        assert toggled["enabled"] is False
        toggled2 = storage.toggle(result["id"])
        assert toggled2["enabled"] is True

    def test_toggle_nonexistent(self, storage):
        assert storage.toggle("nope") is None

    def test_update_run_status(self, storage):
        result = storage.create({"name": "run", "cron_expr": "*", "content": "x"})
        storage.update_run_status(result["id"], "success")
        fetched = storage.get(result["id"])
        assert fetched["last_status"] == "success"

    def test_update_run_status_increment_fail(self, storage):
        result = storage.create({"name": "fail", "cron_expr": "*", "content": "x"})
        storage.update_run_status(result["id"], "failed", increment_fail=True)
        fetched = storage.get(result["id"])
        assert fetched["fail_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# cron/automation.py — templates and validation
# ═══════════════════════════════════════════════════════════════════════════

from xiaopaw.cron.automation import AutomationRegistry, TEMPLATES, _TEMPLATE_MAP


class TestAutomationRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        return AutomationRegistry(db_path=tmp_path / "auto.db")

    def test_list_templates(self, registry):
        templates = registry.list_templates()
        assert len(templates) == len(TEMPLATES)
        assert all("name" in t for t in templates)

    def test_create_task_validation_no_cron(self, registry):
        with pytest.raises(ValueError, match="cron_expr is required"):
            registry.create_task({"name": "test", "content": "x"})

    def test_create_task_validation_no_content(self, registry):
        with pytest.raises(ValueError, match="name or content is required"):
            registry.create_task({"cron_expr": "* * * * *"})

    def test_create_and_list(self, registry):
        registry.create_task({"name": "t1", "cron_expr": "0 * * * *", "content": "hello"})
        tasks = registry.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["name"] == "t1"

    def test_create_from_template(self, registry):
        template_name = TEMPLATES[0]["name"]
        result = registry.create_from_template(template_name)
        assert result["cron_expr"] == TEMPLATES[0]["cron_expr"]

    def test_create_from_template_with_override(self, registry):
        template_name = TEMPLATES[0]["name"]
        result = registry.create_from_template(template_name, {"cron_expr": "0 12 * * *"})
        assert result["cron_expr"] == "0 12 * * *"

    def test_create_from_nonexistent_template(self, registry):
        with pytest.raises(ValueError, match="template not found"):
            registry.create_from_template("nonexistent")

    def test_toggle_task(self, registry):
        result = registry.create_task({"name": "tog", "cron_expr": "*", "content": "x"})
        toggled = registry.toggle_task(result["id"])
        assert toggled["enabled"] is False

    def test_delete_task(self, registry):
        result = registry.create_task({"name": "del", "cron_expr": "*", "content": "x"})
        assert registry.delete_task(result["id"]) is True
        assert registry.get_task(result["id"]) is None

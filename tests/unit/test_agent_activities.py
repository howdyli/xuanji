"""Tests for ActivityRecorder, EventBus publish, and Activity API handler.

Covers: buffer/persist/clear lifecycle, CommunityEvent filtering,
CrewObservabilityAdapter → EventBus integration, graceful no-bus fallback,
API active/history modes, and auth requirement.
All database access is mocked — no real PostgreSQL required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from xiaopaw.event_bus import AgentEvent, CommunityEvent, EventBus, EventPayload
from xiaopaw.hook_framework.crew_adapter import CrewObservabilityAdapter
from xiaopaw.hook_framework.registry import HookRegistry
from xiaopaw.observability.activity_recorder import ActivityRecorder


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def pg_store():
    """Mock pg_store with save_activity / fetch_activities."""
    store = MagicMock()
    store.save_activity = MagicMock()
    store.fetch_activities = MagicMock(return_value=[])
    return store


@pytest.fixture
def recorder(pg_store):
    return ActivityRecorder(pg_store=pg_store)


@pytest.fixture
def session_id():
    return "s-test-001"


def _make_payload(
    event=AgentEvent.TOOL_CALL_START,
    session_id="s-test-001",
    tool_name="search",
    skill_name="flight_search",
    **extra,
) -> EventPayload:
    data = {"tool_name": tool_name, "agent_role": "researcher", "turn_id": "t1", "skill_name": skill_name, **extra}
    return EventPayload(event=event, session_id=session_id, data=data)


# ═══════════════════════════════════════════════════════════════════════════
# ActivityRecorder
# ═══════════════════════════════════════════════════════════════════════════


class TestActivityRecorder:

    def test_activity_recorder_buffers_events(self, recorder, session_id):
        """handle_event 写入内存缓冲区，get_active 可读取。"""
        payload = _make_payload(session_id=session_id)
        recorder.handle_event(payload)

        activities = recorder.get_active(session_id)
        assert len(activities) == 1
        assert activities[0]["event_type"] == AgentEvent.TOOL_CALL_START.value
        assert activities[0]["tool_name"] == "search"
        assert activities[0]["session_id"] == session_id

    def test_activity_recorder_persists_to_pg(self, recorder, pg_store):
        """handle_event 调用 pg_store.save_activity 持久化。"""
        payload = _make_payload()
        recorder.handle_event(payload)

        pg_store.save_activity.assert_called_once()
        saved = pg_store.save_activity.call_args[0][0]
        assert saved["event_type"] == AgentEvent.TOOL_CALL_START.value

    def test_activity_recorder_clear_session(self, recorder, session_id):
        """clear_session 后 get_active 返回空列表。"""
        recorder.handle_event(_make_payload(session_id=session_id))
        assert len(recorder.get_active(session_id)) == 1

        recorder.clear_session(session_id)
        assert recorder.get_active(session_id) == []

    def test_activity_recorder_ignores_non_agent_events(self, recorder, pg_store):
        """CommunityEvent 不写入缓冲区也不持久化。"""
        payload = EventPayload(
            event=CommunityEvent.SKILL_PUBLISHED,
            session_id="s-test-001",
            data={"skill_name": "demo"},
        )
        recorder.handle_event(payload)

        assert recorder.get_active("s-test-001") == []
        pg_store.save_activity.assert_not_called()

    def test_to_activity_struct_fields(self, recorder, session_id):
        """_to_activity 输出的 dict 包含所有必需字段，且 skill_name/agent_role 从 adapter 传入。"""
        payload = _make_payload(
            session_id=session_id,
            tool_name="search",
            skill_name="flight_search",
            agent_role="orchestrator",
        )
        recorder.handle_event(payload)

        activity = recorder.get_active(session_id)[0]
        # 必需字段存在
        for key in ("session_id", "turn_id", "event_type", "agent_role",
                    "tool_name", "skill_name", "status", "duration_ms",
                    "metadata", "created_at"):
            assert key in activity, f"Missing field: {key}"
        # status 枚举值校验
        assert activity["status"] in ("active", "completed")
        # tool_call_start 应为 active
        assert activity["status"] == "active"
        # duration_ms 为 int
        assert isinstance(activity["duration_ms"], int)
        # created_at 为 ISO 格式字符串
        assert "T" in activity["created_at"]
        # skill_name / agent_role 从 adapter payload 透传
        assert activity["skill_name"] == "flight_search"
        assert activity["agent_role"] == "orchestrator"

    def test_activity_recorder_get_history(self, recorder, pg_store, session_id):
        """get_history 委托 pg_store.fetch_activities 并返回结果。"""
        expected = [
            {"event_type": "tool_call_result", "tool_name": "search",
             "status": "completed", "duration_ms": 120},
        ]
        pg_store.fetch_activities.return_value = expected

        result = recorder.get_history(session_id, turn_id="t1", limit=20)

        assert result == expected
        pg_store.fetch_activities.assert_called_once_with(
            session_id, turn_id="t1", limit=20,
        )

    def test_activity_recorder_get_history_no_pg(self):
        """无 pg_store 时 get_history 返回空列表。"""
        rec = ActivityRecorder(pg_store=None)
        assert rec.get_history("s-test-001") == []


# ═══════════════════════════════════════════════════════════════════════════
# EventBus integration via CrewObservabilityAdapter
# ═══════════════════════════════════════════════════════════════════════════


class TestEventBusAdapter:

    @staticmethod
    def _make_adapter(event_bus: EventBus | None) -> CrewObservabilityAdapter:
        registry = MagicMock(spec=HookRegistry)
        registry.dispatch = MagicMock()
        registry.dispatch_gate = MagicMock()
        return CrewObservabilityAdapter(
            registry=registry,
            session_id="s-test-001",
            event_bus=event_bus,
            turn_id="t1",
        )

    def test_eventbus_publish_from_adapter(self):
        """on_before_tool_call 通过 EventBus 发送 TOOL_CALL_START（含 skill_name）。"""
        bus = MagicMock(spec=EventBus)
        adapter = self._make_adapter(bus)

        adapter.on_before_tool_call("search", {"q": "flights"}, skill_name="flight_search")

        bus.publish.assert_called_once()
        payload: EventPayload = bus.publish.call_args[0][0]
        assert payload.event == AgentEvent.TOOL_CALL_START
        assert payload.data["tool_name"] == "search"
        assert payload.data["skill_name"] == "flight_search"
        assert payload.session_id == "s-test-001"

    def test_eventbus_publish_tool_result(self):
        """on_after_tool_call 通过 EventBus 发送 TOOL_CALL_RESULT（含 duration_ms + skill_name）。"""
        bus = MagicMock(spec=EventBus)
        adapter = self._make_adapter(bus)

        # Simulate before→after to populate _tool_start_times
        adapter.on_before_tool_call("search", {"q": "flights"}, skill_name="flight_search")
        bus.publish.reset_mock()

        adapter.on_after_tool_call("search", {"q": "flights"}, "result data", skill_name="flight_search")

        bus.publish.assert_called_once()
        payload: EventPayload = bus.publish.call_args[0][0]
        assert payload.event == AgentEvent.TOOL_CALL_RESULT
        assert payload.data["tool_name"] == "search"
        assert payload.data["skill_name"] == "flight_search"
        assert "duration_ms" in payload.data
        assert isinstance(payload.data["duration_ms"], int)

    def test_adapter_no_eventbus_graceful(self):
        """event_bus=None 时 on_before_tool_call 不报错。"""
        adapter = self._make_adapter(event_bus=None)
        # Should not raise
        adapter.on_before_tool_call("search", {"q": "flights"})


# ═══════════════════════════════════════════════════════════════════════════
# API handler tests
# ═══════════════════════════════════════════════════════════════════════════


class TestActivityAPI:

    @staticmethod
    def _make_request(*, session_id="s-test-001", query_params=None, app_extras=None):
        req = MagicMock()
        req.match_info = {"session_id": session_id}
        req.query = query_params or {}
        req.headers = {}
        req.app = app_extras or {}
        return req

    @pytest.mark.asyncio
    async def test_activity_api_active_mode(self):
        """active 模式返回内存缓冲区中的活动。"""
        from xiaopaw.frontend.routes.activity import handle_agent_activities

        mock_recorder = MagicMock()
        mock_recorder.get_active = MagicMock(return_value=[
            {"event_type": "tool_call_start", "tool_name": "search", "status": "active"},
        ])

        req = self._make_request(
            query_params={"mode": "active"},
            app_extras={"activity_recorder": mock_recorder},
        )
        with patch("xiaopaw.frontend.routes.activity.check_auth", return_value=True):
            resp = await handle_agent_activities(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert len(body["activities"]) == 1
        assert body["activities"][0]["tool_name"] == "search"
        mock_recorder.get_active.assert_called_once_with("s-test-001")

    @pytest.mark.asyncio
    async def test_activity_api_history_mode(self):
        """history 模式从 PG 查询历史活动。"""
        from xiaopaw.frontend.routes.activity import handle_agent_activities

        mock_recorder = MagicMock()
        mock_recorder.get_history = MagicMock(return_value=[
            {"event_type": "tool_call_result", "tool_name": "search", "status": "completed"},
        ])

        req = self._make_request(
            query_params={"mode": "history", "turn_id": "t1", "limit": "20"},
            app_extras={"activity_recorder": mock_recorder},
        )
        with patch("xiaopaw.frontend.routes.activity.check_auth", return_value=True):
            resp = await handle_agent_activities(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert len(body["activities"]) == 1
        assert body["activities"][0]["status"] == "completed"
        mock_recorder.get_history.assert_called_once_with("s-test-001", turn_id="t1", limit=20)

    @pytest.mark.asyncio
    async def test_activity_api_invalid_mode(self):
        """无效 mode 参数返回 400。"""
        from xiaopaw.frontend.routes.activity import handle_agent_activities

        mock_recorder = MagicMock()
        req = self._make_request(
            query_params={"mode": "bogus"},
            app_extras={"activity_recorder": mock_recorder},
        )
        with patch("xiaopaw.frontend.routes.activity.check_auth", return_value=True):
            resp = await handle_agent_activities(req)

        assert resp.status == 400
        body = json.loads(resp.body)
        assert "Invalid mode" in body["error"]
        # recorder 方法不应被调用
        mock_recorder.get_active.assert_not_called()
        mock_recorder.get_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_activity_api_auth_required(self):
        """无认证返回 401。"""
        from xiaopaw.frontend.routes.activity import handle_agent_activities

        req = self._make_request(
            query_params={"mode": "active"},
            app_extras={"activity_recorder": MagicMock()},
        )
        with patch("xiaopaw.frontend.routes.activity.check_auth", return_value=False):
            resp = await handle_agent_activities(req)

        assert resp.status == 401
        body = json.loads(resp.body)
        assert body["error"] == "unauthorized"

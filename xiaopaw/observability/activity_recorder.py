"""ActivityRecorder —— EventBus 全局订阅者，持久化 Agent 执行活动。

订阅 EventBus 的 "*" 事件，过滤 AgentEvent 类型：
1. 写入内存缓冲区（session_id → list[dict]），供轮询 API 零 DB 查询
2. 异步写入 PG agent_activities 表（fire-and-forget）
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from xiaopaw.event_bus import AgentEvent, EventPayload

logger = logging.getLogger(__name__)


class ActivityRecorder:
    """Agent 协作活动记录器。

    通过订阅 EventBus 全局事件流，将 Agent 执行过程中的关键事件
    （启动、工具调用、思考、完成等）持久化到内存缓冲区和 PostgreSQL，
    为前端可视化提供数据源。
    """

    def __init__(self, pg_store: Any | None = None) -> None:
        self._pg_store = pg_store
        self._active: dict[str, list[dict]] = {}
        self._lock = threading.Lock()  # Sub-Crew 子线程安全

    def handle_event(self, payload: EventPayload) -> None:
        """EventBus 全局 handler，过滤 AgentEvent 后记录。"""
        if not isinstance(payload.event, AgentEvent):
            return

        event_type = payload.event.value if isinstance(payload.event, AgentEvent) else str(payload.event)
        activity = self._to_activity(payload)
        session_id = payload.session_id

        with self._lock:
            if session_id not in self._active:
                self._active[session_id] = []

            # ── 回填匹配的开始事件状态 ──────────────────────────────
            if event_type == "tool_call_result":
                tool_name = (payload.data or {}).get("tool_name", "")
                for act in reversed(self._active[session_id]):
                    if (act["event_type"] == "tool_call_start"
                            and act["tool_name"] == tool_name
                            and act["status"] == "active"):
                        act["status"] = "completed"
                        act["duration_ms"] = (payload.data or {}).get("duration_ms", 0)
                        break
            elif event_type == "agent_complete":
                # 回填 agent_started → completed
                for act in self._active[session_id]:
                    if act["event_type"] == "agent_started" and act["status"] == "active":
                        act["status"] = "completed"
                        act["duration_ms"] = (payload.data or {}).get("duration_ms", 0)

                # 从 used_skills 生成 skill_used 活动记录
                used_skills = (payload.data or {}).get("used_skills", [])
                for skill in used_skills:
                    skill_activity = {
                        "session_id": session_id,
                        "turn_id": (payload.data or {}).get("turn_id", ""),
                        "event_type": "skill_used",
                        "agent_role": "orchestrator",
                        "tool_name": "",
                        "skill_name": skill,
                        "status": "completed",
                        "duration_ms": 0,
                        "metadata": {"skill_name": skill},
                        "created_at": payload.timestamp,
                    }
                    self._active[session_id].append(skill_activity)
                    if self._pg_store:
                        try:
                            self._pg_store.save_activity(skill_activity)
                        except Exception as e:
                            logger.warning("Failed to persist skill_used activity: %s", e)

            self._active[session_id].append(activity)

        # 写 PG（fire-and-forget，不阻塞 Agent）
        if self._pg_store:
            try:
                self._pg_store.save_activity(activity)
            except Exception as e:
                logger.warning("Failed to persist activity: %s", e)

    def get_active(self, session_id: str) -> list[dict]:
        """返回当前活跃活动（内存读取）。"""
        with self._lock:
            return list(self._active.get(session_id, []))

    def get_history(self, session_id: str, turn_id: str = "", limit: int = 50) -> list[dict]:
        """从 PG 查询历史活动。"""
        if not self._pg_store:
            return []
        try:
            return self._pg_store.fetch_activities(session_id, turn_id=turn_id, limit=limit)
        except Exception as e:
            logger.warning("Failed to fetch activity history: %s", e)
            return []

    def clear_session(self, session_id: str) -> None:
        """Agent 完成后清除活跃缓冲区。"""
        with self._lock:
            self._active.pop(session_id, None)

    def _to_activity(self, payload: EventPayload) -> dict:
        """将 EventPayload 转换为 activity dict。"""
        event_type = payload.event.value if isinstance(payload.event, AgentEvent) else str(payload.event)
        data = payload.data or {}
        return {
            "session_id": payload.session_id,
            "turn_id": data.get("turn_id", ""),
            "event_type": event_type,
            "agent_role": data.get("agent_role", ""),
            "tool_name": data.get("tool_name", ""),
            "skill_name": data.get("skill_name", ""),
            "status": (
                "active" if event_type in ("agent_started", "tool_call_start", "thinking")
                else "error" if event_type == "agent_error"
                else "completed"
            ),
            "duration_ms": data.get("duration_ms", 0),
            "metadata": data,
            "created_at": payload.timestamp,
        }

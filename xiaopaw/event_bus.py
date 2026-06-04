"""EventBus —— 轻量级事件总线，解耦 Agent 编排层与传输层。

【设计理念】借鉴 Proma 的 AgentEventBus 模式：
Agent 执行引擎通过 EventBus 分发事件，传输层（WebSocket/飞书回调/HTTP SSE）
通过订阅 EventBus 接收事件，两者完全解耦。

【核心收益】
1. 新增渠道（钉钉/微信/Web）时不改 Agent 核心逻辑
2. 独立测试编排层（mock EventBus 即可）
3. 同一事件可被多个订阅者消费（日志 + 前端 + 飞书同时接收）

【与 HookRegistry 的关系】
HookRegistry 是"安全加固层"的事件体系（BEFORE_TOOL_CALL / AFTER_TURN 等），
EventBus 是"业务事件分发层"的事件体系（agent_started / token_stream / tool_result 等）。
两者互补：HookRegistry 管安全，EventBus 管业务。

【事件类型】
    AGENT_STARTED     : Agent 开始处理消息
    AGENT_STREAMING   : Agent 正在流式输出
    AGENT_COMPLETE    : Agent 处理完成
    AGENT_ERROR       : Agent 处理出错
    TOOL_CALL_START   : 工具调用开始
    TOOL_CALL_RESULT  : 工具调用结果
    SESSION_CREATED   : 新会话创建
    TITLE_UPDATED     : 会话标题更新
    THINKING          : Agent 思考中（展示思考指示器）
"""

from __future__ import annotations

import asyncio
import logging
import sys
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class AgentEvent(str, Enum):
    """Agent 业务事件类型。"""

    AGENT_STARTED = "agent_started"
    AGENT_STREAMING = "agent_streaming"
    AGENT_COMPLETE = "agent_complete"
    AGENT_ERROR = "agent_error"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_RESULT = "tool_call_result"
    SESSION_CREATED = "session_created"
    TITLE_UPDATED = "title_updated"
    THINKING = "thinking"


@dataclass(frozen=True)
class EventPayload:
    """事件载荷 —— 不可变，订阅者只能读。"""

    event: AgentEvent
    session_id: str = ""
    routing_key: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def error_message(self) -> str:
        return self.data.get("error", "")

    @property
    def content(self) -> str:
        return self.data.get("content", "")

    @property
    def tool_name(self) -> str:
        return self.data.get("tool_name", "")


# 订阅者类型：同步或异步回调
EventHandler = Callable[[EventPayload], Any]


class EventBus:
    """事件总线 —— 发布/订阅模式。

    核心方法：
    - subscribe(event, handler): 注册订阅者
    - publish(payload): 发布事件（同步/异步均支持）
    - publish_async(payload): 异步发布（await 所有 handler）

    设计特点：
    - handler 异常不影响其他 handler（吞掉异常打 stderr）
    - 支持全局事件（event="*"）订阅所有事件
    - 支持 session 级别过滤（只接收特定 session_id 的事件）
    """

    def __init__(self) -> None:
        # event_type → [(handler, session_filter)]
        self._handlers: dict[str, list[tuple[EventHandler, str | None]]] = defaultdict(list)
        self._handler_count = 0

    def subscribe(
        self,
        event: AgentEvent | str,
        handler: EventHandler,
        session_id: str | None = None,
    ) -> Callable[[], None]:
        """注册事件订阅者。

        Args:
            event: 事件类型，"*" 表示订阅所有事件
            handler: 回调函数（同步或 async 均可）
            session_id: 可选过滤，只接收指定 session 的事件

        Returns:
            取消订阅的函数（调用后移除该 handler）
        """
        key = event.value if isinstance(event, AgentEvent) else str(event)
        self._handlers[key].append((handler, session_id))
        self._handler_count += 1

        def unsubscribe():
            try:
                self._handlers[key].remove((handler, session_id))
                self._handler_count -= 1
            except ValueError:
                pass

        return unsubscribe

    def publish(self, payload: EventPayload) -> None:
        """同步发布事件。

        handler 中的异常被吞掉（打 stderr），不影响后续 handler。
        如果 handler 返回 coroutine（async handler），会尝试用 fire-and-forget 方式调度。
        """
        key = payload.event.value
        for handler, session_filter in self._iter_handlers(key):
            if session_filter and payload.session_id != session_filter:
                continue
            try:
                result = handler(payload)
                # 如果 handler 返回 coroutine，记录 warning（应使用 publish_async）
                if asyncio.iscoroutine(result):
                    logger.warning(
                        "[EventBus] async handler %s called via publish() — "
                        "use publish_async() for async handlers",
                        getattr(handler, "__name__", repr(handler)),
                    )
                    result.close()
            except Exception as e:
                print(
                    f"[EventBus] {key} handler error: {e}\n"
                    f"{traceback.format_exc()}",
                    file=sys.stderr,
                )

    async def publish_async(self, payload: EventPayload) -> None:
        """异步发布事件。

        支持同步和异步 handler：
        - 同步 handler：直接调用
        - 异步 handler：await
        """
        key = payload.event.value
        for handler, session_filter in self._iter_handlers(key):
            if session_filter and payload.session_id != session_filter:
                continue
            try:
                result = handler(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                print(
                    f"[EventBus] {key} handler error: {e}\n"
                    f"{traceback.format_exc()}",
                    file=sys.stderr,
                )

    def _iter_handlers(self, event_key: str):
        """迭代特定事件的 handler + 全局 handler。"""
        # 先执行精确匹配
        yield from self._handlers.get(event_key, [])
        # 再执行全局订阅
        if event_key != "*":
            yield from self._handlers.get("*", [])

    def subscriber_count(self, event: AgentEvent | str | None = None) -> int:
        """返回订阅者数量。"""
        if event is None:
            return self._handler_count
        key = event.value if isinstance(event, AgentEvent) else str(event)
        return len(self._handlers.get(key, []))

    def clear(self) -> None:
        """清除所有订阅者。"""
        self._handlers.clear()
        self._handler_count = 0

    def summary(self) -> dict[str, int]:
        """返回各事件的订阅者数量摘要。"""
        return {
            key: len(handlers)
            for key, handlers in self._handlers.items()
            if handlers
        }


# ---- 便捷工厂函数 ----

def create_event_payload(
    event: AgentEvent,
    session_id: str = "",
    routing_key: str = "",
    **data: Any,
) -> EventPayload:
    """快速创建事件载荷。"""
    return EventPayload(
        event=event,
        session_id=session_id,
        routing_key=routing_key,
        data=data,
    )


# ---- SessionCallbacks 适配层 ----
# 借鉴 Proma 的 SessionCallbacks 接口，提供 onError/onComplete/onTitleUpdated 回调

@dataclass
class SessionCallbacks:
    """会话级回调接口 —— 解耦 Agent 编排与传输层。

    在 Runner 中实例化并绑定到具体的 WebSocket/飞书 sender，
    然后传递给 Agent 执行引擎。引擎只需调用 callbacks 的方法，
    不需要知道消息最终发往哪里。
    """

    on_error: Callable[[str], Any] | None = None
    on_complete: Callable[[str, dict | None], Any] | None = None
    on_title_updated: Callable[[str], Any] | None = None
    on_streaming: Callable[[str], Any] | None = None
    on_thinking: Callable[[], Any] | None = None
    on_tool_start: Callable[[str, dict], Any] | None = None
    on_tool_result: Callable[[str, str, float], Any] | None = None

    def error(self, message: str) -> None:
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                pass

    def complete(self, reply: str, opts: dict | None = None) -> None:
        if self.on_complete:
            try:
                self.on_complete(reply, opts)
            except Exception:
                pass

    def title_updated(self, title: str) -> None:
        if self.on_title_updated:
            try:
                self.on_title_updated(title)
            except Exception:
                pass

    def streaming(self, chunk: str) -> None:
        if self.on_streaming:
            try:
                self.on_streaming(chunk)
            except Exception:
                pass

    def thinking(self) -> None:
        if self.on_thinking:
            try:
                self.on_thinking()
            except Exception:
                pass

    def tool_start(self, tool_name: str, tool_input: dict) -> None:
        if self.on_tool_start:
            try:
                self.on_tool_start(tool_name, tool_input)
            except Exception:
                pass

    def tool_result(self, tool_name: str, result: str, duration_ms: float) -> None:
        if self.on_tool_result:
            try:
                self.on_tool_result(tool_name, result, duration_ms)
            except Exception:
                pass

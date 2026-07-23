"""Runner: per-routing_key serial queue with gen-counter worker lifecycle.

v3 integration: Hook framework fires 5+2 events around agent execution.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from xiaopaw.event_bus import AgentEvent, EventPayload
from xiaopaw.feishu.session_key import routing_type
from xiaopaw.hook_framework.crew_adapter import CrewObservabilityAdapter, set_current_adapter
from xiaopaw.hook_framework.registry import EventType, GuardrailDeny, HookContext, HookRegistry
from xiaopaw.models import InboundMessage, SenderProtocol
from xiaopaw.observability.metrics import agent_latency, inbound_total
from xiaopaw.observability.trace import bind_trace_id
from xiaopaw.session.context_builder import ContextBuilder
from xiaopaw.session.manager import SessionManager
from xiaopaw.session.models import MessageEntry

logger = logging.getLogger(__name__)

AgentFn = Callable[
    [str, list[MessageEntry], str, str, bool],
    Awaitable[tuple[str, list[str]]],
]

_SLASH_COMMANDS = {"/new", "/help", "/status", "/verbose"}


class Runner:
    def __init__(
        self,
        session_mgr: SessionManager,
        sender: SenderProtocol,
        agent_fn: AgentFn,
        idle_timeout: float = 300.0,
        max_queue_size: int = 10,
        data_dir: Path | None = None,
        hook_registry: HookRegistry | None = None,
        event_bus: "EventBus | None" = None,
        role_resolver: "Callable[[InboundMessage], str] | None" = None,
    ) -> None:
        self._session_mgr = session_mgr
        self._sender = sender
        self._agent_fn = agent_fn
        self._idle_timeout = idle_timeout
        self._max_queue_size = max_queue_size
        self._data_dir = data_dir or Path("data")

        self._hook_registry = hook_registry
        self._event_bus = event_bus
        # Optional RBAC role resolver: maps an inbound message to a role string
        # (e.g. "admin"/"editor"/"viewer") consumed by permission_gate. When
        # unset, role stays "" and the gate behaves exactly as before.
        self._role_resolver = role_resolver

        if self._event_bus is None:
            logger.warning(
                "Runner initialized WITHOUT event_bus — "
                "Agent activity events will NOT be published. "
                "ActivityRecorder will receive no events."
            )

        self._queues: dict[str, asyncio.Queue[InboundMessage]] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._queue_gen: dict[str, int] = {}
        self._dispatch_lock = asyncio.Lock()
        self._pending_index_tasks: set[asyncio.Task] = set()
        self._shutting_down = False

    def set_role_resolver(
        self, resolver: "Callable[[InboundMessage], str] | None"
    ) -> None:
        """Install (or clear) the RBAC role resolver after construction.

        The Runner is built before the user store exists (see main.py), so the
        resolver is wired in later once auth is available. Passing ``None``
        restores the default behaviour (role stays "").
        """
        self._role_resolver = resolver

    async def dispatch(self, inbound: InboundMessage) -> None:
        if self._shutting_down:
            logger.warning("dispatch rejected (shutting down): %s", inbound.routing_key)
            return

        async with self._dispatch_lock:
            key = inbound.routing_key
            if key not in self._queues:
                self._queues[key] = asyncio.Queue(maxsize=self._max_queue_size)
                self._queue_gen[key] = 0

            q = self._queues[key]
            if q.full():
                logger.warning("queue full for %s, dropping message", key)
                return

            await q.put(inbound)

            if key not in self._workers or self._workers[key].done():
                self._queue_gen[key] += 1
                gen = self._queue_gen[key]
                self._workers[key] = asyncio.create_task(
                    self._worker(key, gen), name=f"worker-{key}"
                )

    async def _worker(self, key: str, gen: int) -> None:
        logger.info("worker started: %s (gen=%d)", key, gen)
        try:
            while True:
                try:
                    inbound = await asyncio.wait_for(
                        self._queues[key].get(), timeout=self._idle_timeout
                    )
                except asyncio.TimeoutError:
                    break

                await self._handle(inbound)

        except Exception:
            logger.exception("worker error: %s", key)
        finally:
            if self._queue_gen.get(key) == gen:
                self._workers.pop(key, None)
                self._queues.pop(key, None)
                self._queue_gen.pop(key, None)
                logger.info("worker exited: %s (gen=%d, cleaned up)", key, gen)
            else:
                logger.info("worker exited: %s (gen=%d, superseded)", key, gen)

    async def _send_reply(
        self, key: str, text: str, card_msg_id: str | None = None,
    ) -> None:
        """Send reply via card update (preferred) or plain send."""
        try:
            if card_msg_id:
                await self._sender.update_card(card_msg_id, text)
            else:
                await self._sender.send(key, text)
        except Exception:
            logger.warning(
                "failed to send reply for %s (card_msg_id=%s)", key, card_msg_id,
                exc_info=True,
            )

    async def _send_error_reply(
        self, key: str, text: str, card_msg_id: str | None = None,
    ) -> None:
        """Send error reply via card update or plain text (fallback-safe)."""
        try:
            if card_msg_id:
                await self._sender.update_card(card_msg_id, text)
            else:
                await self._sender.send_text(key, text)
        except Exception:
            logger.warning(
                "failed to send error reply for %s (card_msg_id=%s)", key, card_msg_id,
                exc_info=True,
            )

    @staticmethod
    def _classify_and_format_error(exc: Exception) -> str:
        """Classify an exception and return a user-friendly error message."""
        from xiaopaw.utils.error_classifier import classify_exception
        classified = classify_exception(exc)
        exc_str = str(exc)
        if classified.is_quota_exceeded:
            return "抱歉，API 余额不足，请联系管理员充值。"
        if classified.is_rate_limited:
            return "抱歉，请求过于频繁，请稍后重试。"
        if classified.is_context_overflow:
            return "抱歉，对话内容过长，请使用 /new 开启新会话。"
        if "Database initialization error" in exc_str or "unable to open database file" in exc_str:
            logger.error("CrewAI storage error — check CREWAI_STORAGE_DIR and disk permissions")
            return "抱歉，AI 引擎初始化存储失败，请稍后重试或联系管理员。"
        return "抱歉，处理消息时出现了错误，请稍后重试。"

    async def _handle(self, inbound: InboundMessage) -> None:
        token = bind_trace_id(inbound.trace_id)
        start = time.monotonic()
        key = inbound.routing_key

        adapter: CrewObservabilityAdapter | None = None
        card_msg_id: str | None = None
        session = None
        used_skills: list[str] = []
        try:
            # Slash command intercept
            cmd = inbound.content.strip().split()[0].lower() if inbound.content.strip() else ""
            if cmd in _SLASH_COMMANDS:
                reply = await self._handle_slash(cmd, inbound)
                await self._sender.send(key, reply)
                return

            # Get or create session
            session = await self._session_mgr.get_or_create(key)

            # Create Hook adapter (per-request, session_id bound)
            if self._hook_registry:
                # Resolve the caller's RBAC role (best-effort; never blocks the
                # turn on a resolver error).
                role = ""
                if self._role_resolver is not None:
                    try:
                        role = self._role_resolver(inbound) or ""
                    except Exception:
                        logger.warning("role_resolver failed for %s", key, exc_info=True)
                adapter = CrewObservabilityAdapter(
                    registry=self._hook_registry,
                    session_id=session.id,
                    event_bus=self._event_bus,
                    turn_id=inbound.msg_id,
                    role=role,
                )

            # EventBus: AGENT_STARTED
            if self._event_bus:
                logger.debug("[EventBus.Publish] AGENT_STARTED session=%s turn=%s", session.id[:8], inbound.msg_id)
                self._event_bus.publish(EventPayload(
                    event=AgentEvent.AGENT_STARTED,
                    session_id=session.id,
                    data={"agent_role": "orchestrator", "turn_id": inbound.msg_id},
                ))

            # Hook: BEFORE_TURN
            if adapter:
                adapter.on_turn_start(
                    user_message=inbound.content,
                    sender_id=inbound.sender_id,
                )

            # Load history (ContextBuilder used for sliding window when >10 turns)
            history = await self._session_mgr.load_history(session.id)
            if len(history) > 10:
                ContextBuilder(sessions_dir=self._session_mgr._sessions_dir)

            # Send thinking indicator
            card_msg_id = await self._sender.send_thinking(key)

            # EventBus: THINKING
            if self._event_bus:
                logger.debug("[EventBus.Publish] THINKING session=%s turn=%s", session.id[:8], inbound.msg_id)
                self._event_bus.publish(EventPayload(
                    event=AgentEvent.THINKING,
                    session_id=session.id,
                    data={"agent_role": "orchestrator", "turn_id": inbound.msg_id},
                ))

            # Pre-flight safety check via virtual "agent_execution" tool call
            if adapter:
                adapter.on_before_tool_call(
                    tool_name="agent_execution",
                    tool_input={"content": inbound.content[:500]},
                )
                if adapter._pending_deny:
                    pending = adapter._pending_deny
                    adapter._pending_deny = None
                    raise pending

            # Run agent (with adapter available via ContextVar)
            adapter_token = set_current_adapter(adapter) if adapter else None
            try:
                reply, used_skills = await self._agent_fn(
                    inbound.content,
                    history,
                    session.id,
                    key,
                    session.verbose,
                )
            finally:
                if adapter_token is not None:
                    set_current_adapter(None)

            # Hook: AFTER_TOOL_CALL for the agent execution
            if adapter:
                adapter.on_after_tool_call(
                    tool_name="agent_execution",
                    tool_input={"content": inbound.content[:500]},
                    tool_result=reply[:500],
                )

            # Send reply
            await self._send_reply(key, reply, card_msg_id)

            # EventBus: AGENT_COMPLETE
            if self._event_bus:
                elapsed_ms = round((time.monotonic() - start) * 1000)
                logger.debug("[EventBus.Publish] AGENT_COMPLETE session=%s skills=%s duration=%dms", session.id[:8], used_skills, elapsed_ms)
                self._event_bus.publish(EventPayload(
                    event=AgentEvent.AGENT_COMPLETE,
                    session_id=session.id,
                    data={"agent_role": "orchestrator", "duration_ms": elapsed_ms, "turn_id": inbound.msg_id, "used_skills": used_skills},
                ))

            # Persist conversation
            await self._session_mgr.append(
                session.id,
                user=inbound.content,
                feishu_msg_id=inbound.msg_id,
                assistant=reply,
                ts=inbound.ts,
            )

            elapsed = time.monotonic() - start
            agent_latency.labels(routing_type=routing_type(key)).observe(elapsed)

            # Hook: AFTER_TURN
            if adapter and self._hook_registry:
                self._hook_registry.dispatch(
                    EventType.AFTER_TURN,
                    HookContext(
                        event_type=EventType.AFTER_TURN,
                        session_id=session.id,
                        sender_id=inbound.sender_id,
                        duration_ms=elapsed * 1000,
                        metadata={
                            "user_message": inbound.content[:500],
                            "reply": reply[:500],
                        },
                    ),
                )

        except GuardrailDeny as deny:
            elapsed = time.monotonic() - start
            logger.warning("guardrail deny for %s: %s", key, deny)
            deny_reply = f"安全策略拦截：{deny.detail or deny.reason_code}"

            # EventBus: AGENT_ERROR for guardrail deny
            if self._event_bus:
                _sid = session.id if session else ""
                logger.debug("[EventBus.Publish] AGENT_ERROR(deny) session=%s reason=%s", _sid[:8] if _sid else "", deny.reason_code)
                self._event_bus.publish(EventPayload(
                    event=AgentEvent.AGENT_ERROR,
                    session_id=_sid,
                    data={"error": f"guardrail_deny: {deny.reason_code}", "turn_id": inbound.msg_id, "type": "guardrail_deny"},
                ))

            if adapter and self._hook_registry:
                self._hook_registry.dispatch(
                    EventType.AFTER_TURN,
                    HookContext(
                        event_type=EventType.AFTER_TURN,
                        session_id=adapter._session_id,
                        sender_id=inbound.sender_id,
                        duration_ms=elapsed * 1000,
                        metadata={
                            "user_message": inbound.content[:500],
                            "reply": deny_reply,
                            "guardrail_deny": True,
                            "deny_reason": deny.reason_code,
                            "deny_detail": deny.detail,
                        },
                    ),
                )
            await self._send_error_reply(key, deny_reply, card_msg_id)

        except Exception as exc:
            logger.exception("handle error for %s", key)
            error_reply = self._classify_and_format_error(exc)
            await self._send_error_reply(key, error_reply, card_msg_id)

            # EventBus: AGENT_ERROR
            if self._event_bus:
                _sid = session.id if session else ""
                logger.debug("[EventBus.Publish] AGENT_ERROR session=%s error=%s", _sid[:8] if _sid else "", str(exc)[:200])
                self._event_bus.publish(EventPayload(
                    event=AgentEvent.AGENT_ERROR,
                    session_id=_sid,
                    data={"error": str(exc), "turn_id": inbound.msg_id if inbound else ""},
                ))

        finally:
            # SESSION_END cleanup: flush Langfuse data, write audit summary
            if adapter:
                try:
                    adapter.cleanup()
                except GuardrailDeny:
                    pass
            bind_trace_id("-")

    async def _handle_slash(self, cmd: str, inbound: InboundMessage) -> str:
        key = inbound.routing_key

        if cmd == "/new":
            session = await self._session_mgr.create_new_session(key)
            return f"已创建新会话 {session.id}"

        if cmd == "/help":
            return (
                "可用命令：\n"
                "  /new — 创建新会话\n"
                "  /status — 查看当前会话状态\n"
                "  /verbose on|off — 开关详细模式\n"
                "  /help — 显示此帮助"
            )

        if cmd == "/status":
            session_info = self._session_mgr.get_session_info(key)
            if session_info:
                return (
                    f"会话 ID: {session_info.id}\n"
                    f"创建时间: {session_info.created_at}\n"
                    f"消息数: {session_info.message_count}\n"
                    f"详细模式: {'开启' if session_info.verbose else '关闭'}"
                )
            return "当前无活动会话"

        if cmd == "/verbose":
            parts = inbound.content.strip().split()
            on = parts[1].lower() in ("on", "1", "true") if len(parts) > 1 else True
            await self._session_mgr.update_verbose(key, on)
            return f"详细模式已{'开启' if on else '关闭'}"

        return f"未知命令: {cmd}"

    async def shutdown(self) -> None:
        self._shutting_down = True
        logger.info("runner shutting down...")

        for task in self._workers.values():
            task.cancel()
        if self._workers:
            await asyncio.gather(*self._workers.values(), return_exceptions=True)

        for task in self._pending_index_tasks:
            task.cancel()
        if self._pending_index_tasks:
            await asyncio.gather(*self._pending_index_tasks, return_exceptions=True)

        self._workers.clear()
        self._queues.clear()
        logger.info("runner shutdown complete")

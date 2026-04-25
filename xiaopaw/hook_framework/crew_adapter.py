"""CrewObservabilityAdapter: bridges CrewAI hooks to the 5+2 event system.

Mapping:
  on_turn_start     → BEFORE_TURN (once per turn, from Runner)
  @before_llm_call  → BEFORE_LLM (every LLM call, from CrewAI)
  @before_tool_call → BEFORE_TOOL_CALL (via dispatch_gate + pending_deny)
  @after_tool_call  → AFTER_TOOL_CALL
  step_callback     → AFTER_TURN (re-raises pending_deny)
  task_callback     → TASK_COMPLETE (re-raises pending_deny)
  cleanup()         → SESSION_END (re-raises pending_deny)
"""

from contextvars import ContextVar
from typing import Callable

from .registry import EventType, GuardrailDeny, HookContext, HookRegistry

_current_adapter: ContextVar["CrewObservabilityAdapter | None"] = ContextVar(
    "current_hook_adapter", default=None
)


def set_current_adapter(adapter: "CrewObservabilityAdapter | None"):
    return _current_adapter.set(adapter)


def get_current_adapter() -> "CrewObservabilityAdapter | None":
    return _current_adapter.get(None)

_MAX_TEXT = 2000


def _truncate(text: str, limit: int = _MAX_TEXT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated, {len(text)} chars total]"


class CrewObservabilityAdapter:
    def __init__(self, registry: HookRegistry, session_id: str = ""):
        self._registry = registry
        self._session_id = session_id
        self._turn_count = 0
        self._current_turn_has_llm = False
        self._cleaned = False
        self._pending_deny: GuardrailDeny | None = None
        self._last_agent_role = ""
        self._last_prompt_preview = ""

    def on_turn_start(
        self, user_message: str = "", sender_id: str = ""
    ):
        self._turn_count += 1
        self._current_turn_has_llm = True
        self._registry.dispatch(
            EventType.BEFORE_TURN,
            HookContext(
                event_type=EventType.BEFORE_TURN,
                agent_id="runner",
                session_id=self._session_id,
                turn_number=self._turn_count,
                sender_id=sender_id,
                metadata={"user_message": _truncate(user_message, 500)},
            ),
        )

    def on_before_llm(self, agent_role: str = "", messages: list | None = None):
        self._last_agent_role = agent_role

        if not self._current_turn_has_llm:
            self._turn_count += 1
            self._current_turn_has_llm = True
            self._registry.dispatch(
                EventType.BEFORE_TURN,
                HookContext(
                    event_type=EventType.BEFORE_TURN,
                    agent_id=agent_role,
                    session_id=self._session_id,
                    turn_number=self._turn_count,
                ),
            )

        prompt_messages = []
        if messages:
            for m in messages[-10:]:
                if isinstance(m, dict):
                    prompt_messages.append({
                        "role": m.get("role", ""),
                        "content": _truncate(str(m.get("content", "")), 300),
                    })
                else:
                    prompt_messages.append({"content": _truncate(str(m), 300)})

        preview = ""
        if messages:
            last_msg = messages[-1]
            content = last_msg.get("content", "") if isinstance(last_msg, dict) else str(last_msg)
            preview = _truncate(str(content), 500)
        self._last_prompt_preview = preview

        self._registry.dispatch(
            EventType.BEFORE_LLM,
            HookContext(
                event_type=EventType.BEFORE_LLM,
                agent_id=agent_role,
                session_id=self._session_id,
                turn_number=self._turn_count,
                metadata={
                    "prompt_preview": preview,
                    "prompt_messages": prompt_messages,
                },
            ),
        )

    def on_before_tool_call(self, tool_name: str, tool_input: dict | None = None):
        ctx = HookContext(
            event_type=EventType.BEFORE_TOOL_CALL,
            tool_name=tool_name,
            tool_input=dict(tool_input or {}),
            session_id=self._session_id,
            turn_number=self._turn_count,
        )
        try:
            self._registry.dispatch_gate(EventType.BEFORE_TOOL_CALL, ctx)
        except GuardrailDeny as e:
            self._pending_deny = e

    def on_after_tool_call(
        self, tool_name: str, tool_input: dict | None = None, tool_result: str = ""
    ):
        truncated = _truncate(str(tool_result))
        self._registry.dispatch(
            EventType.AFTER_TOOL_CALL,
            HookContext(
                event_type=EventType.AFTER_TOOL_CALL,
                tool_name=tool_name,
                tool_input=dict(tool_input or {}),
                session_id=self._session_id,
                turn_number=self._turn_count,
                metadata={"tool_output": truncated},
            ),
        )

    def make_step_callback(self) -> Callable:
        def callback(step):
            step_output = _truncate(str(getattr(step, "output", "") or ""))
            tool_name = getattr(step, "tool", "") or ""

            try:
                self._registry.dispatch_gate(
                    EventType.AFTER_TURN,
                    HookContext(
                        event_type=EventType.AFTER_TURN,
                        session_id=self._session_id,
                        turn_number=self._turn_count,
                        agent_id=self._last_agent_role,
                        tool_name=tool_name,
                        metadata={
                            "output": step_output,
                            "prompt_preview": self._last_prompt_preview,
                        },
                    ),
                )
            except GuardrailDeny as e:
                self._pending_deny = self._pending_deny or e
            self._current_turn_has_llm = False
            self._last_prompt_preview = ""

            if self._pending_deny:
                pending = self._pending_deny
                self._pending_deny = None
                raise pending

        return callback

    def make_task_callback(self) -> Callable:
        def callback(task_output):
            raw = _truncate(str(getattr(task_output, "raw", str(task_output))))
            desc = getattr(task_output, "description", "") or ""

            self._registry.dispatch(
                EventType.TASK_COMPLETE,
                HookContext(
                    event_type=EventType.TASK_COMPLETE,
                    session_id=self._session_id,
                    task_name=_truncate(str(desc), 500),
                    agent_id=self._last_agent_role,
                    metadata={
                        "raw_output": raw,
                        "task_description": _truncate(str(desc), 500),
                    },
                ),
            )

            if self._pending_deny:
                pending = self._pending_deny
                self._pending_deny = None
                raise pending

        return callback

    def cleanup(self):
        pending = self._pending_deny
        self._pending_deny = None
        if self._cleaned:
            if pending:
                raise pending
            return
        self._cleaned = True
        self._registry.dispatch(
            EventType.SESSION_END,
            HookContext(
                event_type=EventType.SESSION_END,
                session_id=self._session_id,
            ),
        )
        if pending:
            raise pending

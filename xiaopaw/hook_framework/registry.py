"""EventType + HookContext + HookRegistry + GuardrailDeny.

Core dispatch engine for the 5+2 Hook event system.
"""

import sys
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Callable


class EventType(Enum):
    BEFORE_TURN = "before_turn"
    BEFORE_LLM = "before_llm"
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    AFTER_TURN = "after_turn"
    TASK_COMPLETE = "task_complete"
    SESSION_END = "session_end"


class DenyReason(str, Enum):
    BUDGET_EXCEEDED = "budget_exceeded"
    LOOP_DETECTED = "loop_detected"
    SANDBOX_VIOLATION = "sandbox_violation"
    PERMISSION_DENIED = "permission_denied"
    PROMPT_INJECTION = "prompt_injection"


class GuardrailDeny(Exception):
    def __init__(self, reason_code: str | DenyReason, detail: str = ""):
        self.reason_code = reason_code.value if isinstance(reason_code, DenyReason) else reason_code
        self.detail = detail
        super().__init__(f"[{self.reason_code}] {detail}")


@dataclass(frozen=True)
class HookContext:
    event_type: EventType
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    agent_id: str = ""
    task_name: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: float = 0
    success: bool = True
    session_id: str = ""
    turn_number: int = 0
    sender_id: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "tool_input", MappingProxyType(dict(self.tool_input)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class HookRegistry:
    def __init__(self):
        self._handlers: dict[EventType, list[tuple[Callable, bool]]] = defaultdict(list)
        self._handler_names: dict[EventType, list[str]] = defaultdict(list)

    def register(
        self,
        event_type: EventType,
        handler: Callable,
        name: str = "",
        fail_closed: bool = False,
    ):
        self._handlers[event_type].append((handler, fail_closed))
        self._handler_names[event_type].append(
            name or getattr(handler, "__name__", repr(handler))
        )

    def dispatch(self, event_type: EventType, context: HookContext):
        for handler, _fail_closed in self._handlers[event_type]:
            try:
                handler(context)
            except Exception as e:
                print(
                    f"[HookRegistry] {event_type.value} handler error: {e}\n"
                    f"{traceback.format_exc()}",
                    file=sys.stderr,
                )

    def dispatch_gate(self, event_type: EventType, context: HookContext):
        for handler, fail_closed in self._handlers[event_type]:
            try:
                handler(context)
            except GuardrailDeny:
                raise
            except Exception as e:
                if fail_closed:
                    raise GuardrailDeny(
                        DenyReason.SANDBOX_VIOLATION,
                        f"Security handler failed (fail-closed): {e}",
                    ) from e
                print(
                    f"[HookRegistry] {event_type.value} handler error: {e}",
                    file=sys.stderr,
                )

    def handler_count(self, event_type: EventType) -> int:
        return len(self._handlers[event_type])

    def summary(self) -> dict[str, list[str]]:
        return {
            et.value: list(names)
            for et, names in self._handler_names.items()
            if names
        }

"""Structured event log: one JSON line per Hook event to stderr."""

import json
import sys
from datetime import datetime, timezone


def _emit(event_data: dict) -> None:
    event_data["timestamp"] = datetime.now(timezone.utc).isoformat()
    try:
        print(json.dumps(event_data, ensure_ascii=False, default=str), file=sys.stderr)
    except Exception:
        pass


def before_turn_handler(ctx) -> None:
    _emit({
        "event": "before_turn",
        "session_id": ctx.session_id,
        "turn": ctx.turn_number,
        "agent_id": ctx.agent_id,
    })


def before_llm_handler(ctx) -> None:
    _emit({
        "event": "before_llm",
        "session_id": ctx.session_id,
        "turn": ctx.turn_number,
        "agent_id": ctx.agent_id,
        "input_tokens": ctx.input_tokens,
    })


def after_tool_handler(ctx) -> None:
    _emit({
        "event": "after_tool_call",
        "session_id": ctx.session_id,
        "turn": ctx.turn_number,
        "tool_name": ctx.tool_name,
        "success": ctx.success,
        "duration_ms": ctx.duration_ms,
    })

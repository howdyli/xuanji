"""Langfuse trace handler: maps 5+2 Hook events to Langfuse traces via REST ingestion.

Trace hierarchy:
  Session (sessionId) → Trace (per turn) → GENERATION (per LLM call) + SPAN (per tool call)
"""

import base64
import json
import logging
import os
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock

logger = logging.getLogger(__name__)

_LANGFUSE_HOST = os.environ.get("XIAOPAW_LANGFUSE_BASE_URL", "") or os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3000")
_LANGFUSE_PK = os.environ.get("XIAOPAW_LANGFUSE_PUBLIC_KEY", "") or os.environ.get("LANGFUSE_PUBLIC_KEY", "")
_LANGFUSE_SK = os.environ.get("XIAOPAW_LANGFUSE_SECRET_KEY", "") or os.environ.get("LANGFUSE_SECRET_KEY", "")
_ENABLED = os.environ.get("TRACE_TO_LANGFUSE", "").lower() in ("1", "true")

try:
    from xiaopaw.observability.trace import trace_id_var as _trace_id_var
except ImportError:
    _trace_id_var = ContextVar("trace_id", default="-")

_gen_id_var: ContextVar[str] = ContextVar("lf_gen_id", default="")
_gen_count_var: ContextVar[int] = ContextVar("lf_gen_count", default=0)

_batch_lock = Lock()
_batch_buffer: list[dict] = []
_MAX_BATCH = 20


def _auth_header() -> str:
    return base64.b64encode(f"{_LANGFUSE_PK}:{_LANGFUSE_SK}".encode()).decode()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_trace_id(ctx) -> str:
    trace_id = _trace_id_var.get("-")
    if trace_id == "-":
        trace_id = ctx.session_id
    return trace_id or ""


def _flush_batch(events: list[dict]) -> None:
    if not events:
        return
    try:
        import requests

        resp = requests.post(
            f"{_LANGFUSE_HOST}/api/public/ingestion",
            headers={
                "Authorization": f"Basic {_auth_header()}",
                "Content-Type": "application/json",
            },
            json={"batch": events},
            timeout=5,
        )
        if resp.status_code not in (200, 207):
            logger.warning("langfuse ingestion failed: %d %s", resp.status_code, resp.text[:200])
        else:
            body = resp.json()
            errors = body.get("errors", [])
            if errors:
                logger.warning("langfuse ingestion partial errors: %s", errors[:3])
    except Exception:
        logger.debug("langfuse ingestion error (non-blocking)", exc_info=True)


def _enqueue(event: dict) -> None:
    if "id" not in event:
        event["id"] = uuid.uuid4().hex
    if "timestamp" not in event:
        event["timestamp"] = _now_iso()

    to_send = None
    with _batch_lock:
        _batch_buffer.append(event)
        if len(_batch_buffer) >= _MAX_BATCH:
            to_send = list(_batch_buffer)
            _batch_buffer.clear()
    if to_send:
        _flush_batch(to_send)


def before_turn_handler(ctx) -> None:
    """BEFORE_TURN: create the trace for this turn with user message."""
    if not _ENABLED or not _LANGFUSE_PK:
        return

    trace_id = _get_trace_id(ctx)
    if not trace_id:
        return

    _gen_count_var.set(0)
    _gen_id_var.set("")

    user_message = ctx.metadata.get("user_message", "")

    _enqueue({
        "type": "trace-create",
        "body": {
            "id": trace_id,
            "name": f"xiaopaw-turn-{ctx.turn_number}",
            "sessionId": ctx.session_id,
            "userId": ctx.sender_id or ctx.session_id,
            "input": {"message": user_message} if user_message else None,
            "metadata": {
                "source": "xiaopaw-v2",
                "turn": ctx.turn_number,
            },
        },
    })


def before_llm_handler(ctx) -> None:
    """BEFORE_LLM: create a GENERATION observation for each LLM call."""
    if not _ENABLED or not _LANGFUSE_PK:
        return

    trace_id = _get_trace_id(ctx)
    if not trace_id:
        return

    count = _gen_count_var.get(0) + 1
    _gen_count_var.set(count)

    gen_id = uuid.uuid4().hex
    _gen_id_var.set(gen_id)

    prompt_messages = ctx.metadata.get("prompt_messages", [])
    prompt_preview = ctx.metadata.get("prompt_preview", "")

    gen_input = None
    if prompt_messages:
        gen_input = {"messages": prompt_messages}
    elif prompt_preview:
        gen_input = {"prompt": prompt_preview}

    _enqueue({
        "type": "generation-create",
        "body": {
            "id": gen_id,
            "traceId": trace_id,
            "name": f"llm-call-{count}",
            "startTime": _now_iso(),
            "model": "qwen3-max",
            "input": gen_input,
            "metadata": {
                "agent_id": ctx.agent_id,
                "turn": ctx.turn_number,
                "call_number": count,
            },
        },
    })


def after_tool_handler(ctx) -> None:
    """AFTER_TOOL_CALL: create a SPAN for the tool call + update generation."""
    if not _ENABLED or not _LANGFUSE_PK:
        return

    trace_id = _get_trace_id(ctx)
    if not trace_id:
        return

    tool_output = ctx.metadata.get("tool_output", "")
    tool_input_data = dict(ctx.tool_input) if ctx.tool_input else {}

    gen_id = _gen_id_var.get("")
    if gen_id:
        _enqueue({
            "type": "generation-update",
            "body": {
                "id": gen_id,
                "traceId": trace_id,
                "endTime": _now_iso(),
                "output": tool_output or None,
            },
        })
        _gen_id_var.set("")

    if ctx.tool_name == "agent_execution":
        user_msg = tool_input_data.get("content", "")
        _enqueue({
            "type": "trace-create",
            "body": {
                "id": trace_id,
                "input": {"message": user_msg} if user_msg else None,
                "output": {"reply": tool_output} if tool_output else None,
            },
        })

    if ctx.tool_name != "final_answer":
        _enqueue({
            "type": "span-create",
            "body": {
                "id": uuid.uuid4().hex,
                "traceId": trace_id,
                "name": ctx.tool_name or "unknown_tool",
                "startTime": _now_iso(),
                "endTime": _now_iso(),
                "input": tool_input_data or None,
                "output": {"result": tool_output, "success": ctx.success} if tool_output else {"success": ctx.success},
                "level": "DEFAULT" if ctx.success else "ERROR",
                "metadata": {
                    "tool_name": ctx.tool_name,
                    "duration_ms": ctx.duration_ms,
                },
            },
        })

    with _batch_lock:
        pending = list(_batch_buffer)
        _batch_buffer.clear()
    _flush_batch(pending)


def after_turn_handler(ctx) -> None:
    """AFTER_TURN: update trace with final output and duration, then flush."""
    if not _ENABLED or not _LANGFUSE_PK:
        return

    trace_id = _get_trace_id(ctx)
    if not trace_id:
        return

    user_msg = ctx.metadata.get("user_message", "")
    reply = ctx.metadata.get("reply", "")

    body: dict = {"id": trace_id}
    if user_msg:
        body["input"] = {"message": user_msg}
    if reply:
        body["output"] = {"reply": reply}
    if ctx.duration_ms:
        body.setdefault("metadata", {})["duration_ms"] = ctx.duration_ms

    _enqueue({"type": "trace-create", "body": body})

    gen_id = _gen_id_var.get("")
    if gen_id and reply:
        _enqueue({
            "type": "generation-update",
            "body": {
                "id": gen_id,
                "traceId": trace_id,
                "endTime": _now_iso(),
                "output": reply,
            },
        })
        _gen_id_var.set("")

    with _batch_lock:
        pending = list(_batch_buffer)
        _batch_buffer.clear()
    _flush_batch(pending)


def flush_and_close(ctx) -> None:
    """SESSION_END: flush remaining events."""
    if not _ENABLED or not _LANGFUSE_PK:
        return

    with _batch_lock:
        remaining = list(_batch_buffer)
        _batch_buffer.clear()

    trace_id = _get_trace_id(ctx)
    if trace_id:
        remaining.append({
            "id": uuid.uuid4().hex,
            "type": "span-create",
            "timestamp": _now_iso(),
            "body": {
                "id": uuid.uuid4().hex,
                "traceId": trace_id,
                "name": "session_end",
                "startTime": _now_iso(),
                "endTime": _now_iso(),
                "metadata": {"event": "session_end", "session_id": ctx.session_id},
            },
        })

    _flush_batch(remaining)

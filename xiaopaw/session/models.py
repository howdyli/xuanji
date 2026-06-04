"""Session data models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _new_session_id() -> str:
    return f"s-{uuid.uuid4().hex[:12]}"


def _new_dated_session_id(existing_ids: set[str] | None = None) -> str:
    """Generate a session ID using date + sequence format.

    Format: s-YYYYMMDD-NNN (e.g. s-20260603-001)
    The sequence counter is determined by checking existing IDs.
    """
    from datetime import date
    today = date.today()
    prefix = f"s-{today.strftime('%Y%m%d')}-"

    # Find the highest existing sequence for today
    max_seq = 0
    if existing_ids:
        for eid in existing_ids:
            if eid.startswith(prefix):
                try:
                    seq = int(eid[len(prefix):])
                    max_seq = max(max_seq, seq)
                except (ValueError, IndexError):
                    pass

    return f"{prefix}{max_seq + 1:03d}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MessageEntry:
    role: str  # "user" | "assistant"
    content: str
    ts: int  # milliseconds
    feishu_msg_id: str | None = None


@dataclass(frozen=True)
class SessionEntry:
    id: str = field(default_factory=_new_session_id)
    created_at: str = field(default_factory=_now_iso)
    title: str = ""
    verbose: bool = False
    message_count: int = 0


@dataclass(frozen=True)
class RoutingEntry:
    active_session_id: str = ""
    sessions: list[SessionEntry] = field(default_factory=list)

"""SecurityAuditLogger: append-only JSONL audit log."""

import json
import os
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


class SecurityAuditLogger:
    def __init__(self, audit_file: str | Path | None = None):
        env_path = os.environ.get("SECURITY_AUDIT_FILE")
        if env_path:
            self._audit_file = Path(env_path)
        elif audit_file:
            self._audit_file = Path(audit_file)
        else:
            self._audit_file = None
        self._events: deque[dict] = deque(maxlen=10000)

    def record_event(self, security_event: str, **kwargs):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "security_event": security_event,
            **kwargs,
        }
        self._events.append(entry)
        self._write(entry)

    def session_end_handler(self, ctx):
        events_by_type: dict[str, int] = {}
        for e in self._events:
            t = e["security_event"]
            events_by_type[t] = events_by_type.get(t, 0) + 1

        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "security_event": "session_summary",
            "session_id": ctx.session_id,
            "total_security_events": len(self._events),
            "events_by_type": events_by_type,
        }
        self._write(summary)

    def _write(self, entry: dict):
        if self._audit_file is None:
            return
        try:
            with open(self._audit_file, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"[SecurityAuditLogger] write error: {e}", file=sys.stderr)

    def get_metrics(self) -> dict:
        events_by_type: dict[str, int] = {}
        for e in self._events:
            t = e["security_event"]
            events_by_type[t] = events_by_type.get(t, 0) + 1
        return {
            "total_security_events": len(self._events),
            "events_by_type": events_by_type,
        }

"""Session manager: index.json + JSONL per-session storage."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, replace
from pathlib import Path

from xiaopaw.session.models import MessageEntry, RoutingEntry, SessionEntry, _new_dated_session_id

logger = logging.getLogger(__name__)

_LRU_MAX = 1000


class _LRULockCache:
    """Bounded LRU cache for per-session asyncio.Lock instances."""

    def __init__(self, maxsize: int = _LRU_MAX) -> None:
        self._maxsize = maxsize
        self._cache: dict[str, asyncio.Lock] = {}

    def get(self, key: str) -> asyncio.Lock:
        if key in self._cache:
            lock = self._cache.pop(key)
            self._cache[key] = lock
            return lock
        if len(self._cache) >= self._maxsize:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        lock = asyncio.Lock()
        self._cache[key] = lock
        return lock


class SessionManager:
    def __init__(self, data_dir: Path, max_active_sessions: int = _LRU_MAX) -> None:
        self._data_dir = Path(data_dir)
        self._sessions_dir = self._data_dir / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._sessions_dir / "index.json"
        self._index_lock = asyncio.Lock()
        self._jsonl_locks = _LRULockCache(maxsize=max_active_sessions)
        self._index: dict[str, RoutingEntry] = {}
        self._load_index()

    def _load_index(self) -> None:
        if self._index_path.exists():
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
            for rk, entry in raw.items():
                sessions = [SessionEntry(**s) for s in entry.get("sessions", [])]
                self._index[rk] = RoutingEntry(
                    active_session_id=entry["active_session_id"],
                    sessions=sessions,
                )

    def _save_index(self) -> None:
        data = {}
        for rk, entry in self._index.items():
            data[rk] = {
                "active_session_id": entry.active_session_id,
                "sessions": [asdict(s) for s in entry.sessions],
            }
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(self._index_path)

    async def get_or_create(self, routing_key: str) -> SessionEntry:
        async with self._index_lock:
            entry = self._index.get(routing_key)
            if entry and entry.active_session_id:
                for s in entry.sessions:
                    if s.id == entry.active_session_id:
                        return s
            return await self._create_session_locked(routing_key)

    async def activate_session(self, session_id: str, routing_key: str) -> SessionEntry | None:
        """Activate an existing session for the given routing_key.

        If the session belongs to a different routing_key, it will be
        adopted under the new one. Returns None if session_id doesn't exist.
        """
        target: SessionEntry | None = None
        # Search across all routing keys
        for rk, entry in list(self._index.items()):
            for s in entry.sessions:
                if s.id == session_id:
                    target = s
                    break
            if target:
                break
        if target is None:
            return None

        async with self._index_lock:
            # Set active session for the requested routing_key
            entry = self._index.get(routing_key)
            existing_ids = {s.id for s in entry.sessions} if entry else set()
            if session_id not in existing_ids:
                # Adopt session into this routing_key
                sessions = list(entry.sessions) + [target] if entry else [target]
                self._index[routing_key] = RoutingEntry(
                    active_session_id=session_id, sessions=sessions
                )
            else:
                self._index[routing_key] = RoutingEntry(
                    active_session_id=session_id, sessions=entry.sessions
                )
            self._save_index()
        return target

    async def get_session_by_id(self, session_id: str) -> SessionEntry | None:
        """Find a session by ID regardless of routing_key."""
        for rk, entry in self._index.items():
            for s in entry.sessions:
                if s.id == session_id:
                    return s
        return None

    async def create_new_session(self, routing_key: str) -> SessionEntry:
        async with self._index_lock:
            return await self._create_session_locked(routing_key)

    async def _create_session_locked(self, routing_key: str) -> SessionEntry:
        # Collect all existing session IDs for date-based numbering
        existing_ids: set[str] = set()
        for entry in self._index.values():
            for s in entry.sessions:
                existing_ids.add(s.id)

        session = SessionEntry(id=_new_dated_session_id(existing_ids))
        entry = self._index.get(routing_key)
        if entry:
            sessions = list(entry.sessions) + [session]
            self._index[routing_key] = RoutingEntry(
                active_session_id=session.id, sessions=sessions
            )
        else:
            self._index[routing_key] = RoutingEntry(
                active_session_id=session.id, sessions=[session]
            )
        self._save_index()
        logger.info("created session %s for %s", session.id, routing_key)
        return session

    async def update_verbose(self, routing_key: str, verbose: bool) -> None:
        async with self._index_lock:
            entry = self._index.get(routing_key)
            if not entry:
                return
            sessions = [
                replace(s, verbose=verbose) if s.id == entry.active_session_id else s
                for s in entry.sessions
            ]
            self._index[routing_key] = replace(entry, sessions=sessions)
            self._save_index()

    async def load_history(
        self, session_id: str, max_turns: int = 20
    ) -> list[MessageEntry]:
        jsonl_path = self._sessions_dir / f"{session_id}.jsonl"
        if not jsonl_path.exists():
            return []

        def _read() -> list[MessageEntry]:
            lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
            entries: list[MessageEntry] = []
            for line in lines:
                if not line.strip():
                    continue
                data = json.loads(line)
                if "role" in data:
                    entries.append(MessageEntry(**data))
            tail = max_turns * 2
            return entries[-tail:] if len(entries) > tail else entries

        return await asyncio.to_thread(_read)

    async def append(
        self,
        session_id: str,
        *,
        user: str,
        feishu_msg_id: str | None = None,
        assistant: str,
        ts: int = 0,
    ) -> None:
        lock = self._jsonl_locks.get(session_id)
        async with lock:
            jsonl_path = self._sessions_dir / f"{session_id}.jsonl"
            user_entry = MessageEntry(
                role="user", content=user, ts=ts, feishu_msg_id=feishu_msg_id
            )
            asst_entry = MessageEntry(role="assistant", content=assistant, ts=ts)

            def _write() -> None:
                with jsonl_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(user_entry), ensure_ascii=False) + "\n")
                    f.write(json.dumps(asdict(asst_entry), ensure_ascii=False) + "\n")

            await asyncio.to_thread(_write)

        async with self._index_lock:
            for rk, re_ in self._index.items():
                if re_.active_session_id == session_id:
                    sessions = []
                    for s in re_.sessions:
                        if s.id == session_id:
                            # 首条消息（message_count == 0）：提取 user 消息前 50 字符作标题
                            kwargs: dict = {"message_count": s.message_count + 2}
                            if s.message_count == 0:
                                title_raw = user.strip()[:50]
                                # 去掉多余空白，保留可读片段
                                kwargs["title"] = " ".join(title_raw.split())
                            sessions.append(replace(s, **kwargs))
                        else:
                            sessions.append(s)
                    self._index[rk] = replace(re_, sessions=sessions)
                    self._save_index()
                    break

    async def clear_all(self) -> None:
        async with self._index_lock:
            self._index.clear()
            self._save_index()

    def get_session_info(self, routing_key: str) -> SessionEntry | None:
        entry = self._index.get(routing_key)
        if not entry:
            return None
        for s in entry.sessions:
            if s.id == entry.active_session_id:
                return s
        return None

    def list_all_sessions(self) -> list[dict]:
        """Return all sessions across all routing keys, newest first.

        Each dict has keys expected by the frontend API: id, title,
        message_count, updated_at (str), routing_key.
        """
        result: list[dict] = []
        for rk, entry in self._index.items():
            for s in entry.sessions:
                title = s.title
                # Backfill: if session has messages but no title, read first user message
                if not title and s.message_count > 0:
                    title = self._extract_title_from_jsonl(s.id)
                result.append({
                    "id": s.id,
                    "title": title,
                    "message_count": s.message_count,
                    "updated_at": s.created_at,
                    "routing_key": rk,
                })
        # Sort newest first (ISO string comparison works for same zone)
        result.sort(key=lambda x: x["updated_at"], reverse=True)
        return result

    def _extract_title_from_jsonl(self, session_id: str) -> str:
        """Extract title from the first user message in the JSONL file."""
        jsonl_path = self._sessions_dir / f"{session_id}.jsonl"
        if not jsonl_path.exists():
            return ""
        try:
            line = jsonl_path.read_text(encoding="utf-8").strip().split("\n")[0]
            if not line:
                return ""
            data = json.loads(line)
            if data.get("role") == "user" and data.get("content"):
                raw = data["content"].strip()[:50]
                return " ".join(raw.split())
        except Exception:
            pass
        return ""

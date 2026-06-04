"""PostgreSQL store for conversations and sessions (ElectricSQL compatible)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PGStore:
    """Persist conversations and sessions to PostgreSQL for ElectricSQL sync.

    ElectricSQL reads via Postgres logical replication, so writes here
    are automatically synced to the frontend's local PGlite database.
    """

    def __init__(self, dsn: str = "") -> None:
        self._dsn = dsn
        self._available = False
        self._conn = None
        if dsn:
            self._connect()

    def _connect(self) -> None:
        try:
            import psycopg2
            self._conn = psycopg2.connect(self._dsn)
            self._available = True
            logger.info("PGStore: connected to PostgreSQL")
        except Exception as exc:
            logger.warning("PGStore: PostgreSQL unavailable (%s), fallback to JSONL", exc)
            self._available = False

    def _ensure_connection(self) -> bool:
        if self._available and self._conn:
            try:
                self._conn.cursor().execute("SELECT 1")
                return True
            except Exception:
                pass
        # Retry connect
        self._connect()
        return self._available

    async def save_conversation(
        self,
        msg_id: str,
        session_id: str,
        routing_key: str,
        role: str,
        content: str,
    ) -> None:
        """Save a single message to the conversations table."""
        if not self._ensure_connection():
            return
        try:
            import psycopg2
            with self._conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO conversations (id, session_id, routing_key, role, content)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO NOTHING""",
                    (msg_id, session_id, routing_key, role, content),
                )
            self._conn.commit()
        except psycopg2.Error as exc:
            self._conn.rollback()
            logger.warning("PGStore: save_conversation failed: %s", exc)

    async def save_session(
        self,
        session_id: str,
        routing_key: str,
        title: str = "",
        message_count: int = 0,
    ) -> None:
        """Upsert a session record."""
        if not self._ensure_connection():
            return
        try:
            import psycopg2
            with self._conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO sessions (id, routing_key, title, message_count, updated_at)
                       VALUES (%s, %s, %s, %s, NOW())
                       ON CONFLICT (id) DO UPDATE SET
                           message_count = EXCLUDED.message_count,
                           updated_at = NOW()""",
                    (session_id, routing_key, title, message_count),
                )
            self._conn.commit()
        except psycopg2.Error as exc:
            self._conn.rollback()
            logger.warning("PGStore: save_session failed: %s", exc)

    async def fetch_conversations(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch conversations for a session."""
        if not self._ensure_connection():
            return []
        try:
            import psycopg2
            import psycopg2.extras
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, session_id, routing_key, role, content, created_at
                       FROM conversations
                       WHERE session_id = %s
                       ORDER BY created_at ASC
                       LIMIT %s""",
                    (session_id, limit),
                )
                return list(cur.fetchall())
        except psycopg2.Error as exc:
            logger.warning("PGStore: fetch_conversations failed: %s", exc)
            return []

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass


class JSONLStore:
    """File-based fallback store when PostgreSQL is unavailable."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._conv_dir = data_dir / "conversations"
        self._conv_dir.mkdir(parents=True, exist_ok=True)

    async def save_conversation(
        self,
        msg_id: str,
        session_id: str,
        routing_key: str,
        role: str,
        content: str,
    ) -> None:
        session_dir = self._conv_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "id": msg_id,
            "session_id": session_id,
            "routing_key": routing_key,
            "role": role,
            "content": content,
        }
        path = session_dir / f"{msg_id}.json"
        import asyncio
        await asyncio.to_thread(path.write_text, json.dumps(entry, ensure_ascii=False), encoding="utf-8")

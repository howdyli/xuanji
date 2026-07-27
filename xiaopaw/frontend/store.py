"""PostgreSQL store for conversations and sessions (ElectricSQL compatible)."""

from __future__ import annotations

import asyncio
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
        self._dsn = (dsn or "").strip()
        self._available = False
        self._conn = None
        # Skip connection for empty or unexpanded placeholder DSNs (e.g. an
        # unresolved "${MEMORY_DB_DSN:-}"), which would otherwise trigger
        # repeated failed-connect warnings on every operation.
        if self._dsn and "${" not in self._dsn:
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
            def _execute():
                with self._conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO conversations (id, session_id, routing_key, role, content)
                           VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT (id) DO NOTHING""",
                        (msg_id, session_id, routing_key, role, content),
                    )
                self._conn.commit()
            await asyncio.to_thread(_execute)
        except psycopg2.Error as exc:
            self._conn.rollback()
            logger.warning("PGStore: save_conversation failed: %s", exc)

    async def save_session(
        self,
        session_id: str,
        routing_key: str,
        title: str = "",
        message_count: int = 0,
        org_id: int | None = None,
        status: str = "completed",
    ) -> None:
        """Upsert a session record."""
        if not self._ensure_connection():
            return
        try:
            import psycopg2
            def _execute():
                with self._conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO sessions (id, routing_key, title, message_count, org_id, status, updated_at)
                           VALUES (%s, %s, %s, %s, %s, %s, NOW())
                           ON CONFLICT (id) DO UPDATE SET
                               message_count = EXCLUDED.message_count,
                               org_id = COALESCE(sessions.org_id, EXCLUDED.org_id),
                               status = EXCLUDED.status,
                               updated_at = NOW()""",
                        (session_id, routing_key, title, message_count, org_id, status),
                    )
                self._conn.commit()
            await asyncio.to_thread(_execute)
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
            def _execute():
                with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """SELECT id, session_id, routing_key, role, content, created_at
                           FROM conversations
                           WHERE session_id = %s
                           ORDER BY created_at ASC
                           LIMIT %s""",
                        (session_id, limit),
                    )
                    return [dict(r) for r in cur.fetchall()]
            return await asyncio.to_thread(_execute)
        except psycopg2.Error as exc:
            logger.warning("PGStore: fetch_conversations failed: %s", exc)
            return []

    # ── agent_activities 表读写 ────────────────────────────────────────────

    def save_activity(self, activity: dict) -> None:
        """INSERT INTO agent_activities（同步，供 ActivityRecorder fire-and-forget 调用）。"""
        if not self._ensure_connection():
            return
        try:
            import psycopg2
            with self._conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_activities
                           (session_id, turn_id, event_type, agent_role,
                            tool_name, skill_name, status, duration_ms,
                            metadata, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (
                        activity.get("session_id", ""),
                        activity.get("turn_id", ""),
                        activity.get("event_type", ""),
                        activity.get("agent_role", ""),
                        activity.get("tool_name", ""),
                        activity.get("skill_name", ""),
                        activity.get("status", ""),
                        activity.get("duration_ms", 0),
                        json.dumps(activity.get("metadata", {}), ensure_ascii=False),
                        activity.get("created_at", ""),
                    ),
                )
            self._conn.commit()
        except psycopg2.Error as exc:
            self._conn.rollback()
            logger.warning("PGStore: save_activity failed: %s", exc)

    def fetch_activities(
        self,
        session_id: str,
        turn_id: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """SELECT from agent_activities WHERE session_id（同步，供 ActivityRecorder 调用）。"""
        if not self._ensure_connection():
            return []
        try:
            import psycopg2
            import psycopg2.extras
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if turn_id:
                    cur.execute(
                        """SELECT session_id, turn_id, event_type, agent_role,
                                  tool_name, skill_name, status, duration_ms,
                                  metadata, created_at
                           FROM agent_activities
                           WHERE session_id = %s AND turn_id = %s
                           ORDER BY created_at ASC
                           LIMIT %s""",
                        (session_id, turn_id, limit),
                    )
                else:
                    cur.execute(
                        """SELECT session_id, turn_id, event_type, agent_role,
                                  tool_name, skill_name, status, duration_ms,
                                  metadata, created_at
                           FROM agent_activities
                           WHERE session_id = %s
                           ORDER BY created_at ASC
                           LIMIT %s""",
                        (session_id, limit),
                    )
                rows = cur.fetchall()
                # created_at comes back as a datetime from PG; normalize it to an
                # ISO string so callers can json.dumps the rows directly (matching
                # the in-memory activity format where created_at is already a string).
                results: list[dict[str, Any]] = []
                for r in rows:
                    row = dict(r)
                    created = row.get("created_at")
                    if hasattr(created, "isoformat"):
                        row["created_at"] = created.isoformat()
                    results.append(row)
                return results
        except psycopg2.Error as exc:
            logger.warning("PGStore: fetch_activities failed: %s", exc)
            return []

    def migrate_legacy_routing_keys(self, target_routing_key: str) -> None:
        """Migrate old p2p:web_user sessions to the target user's routing_key.

        Runs once at startup; only updates the sessions table.
        """
        if not self._ensure_connection():
            return
        try:
            import psycopg2
            with self._conn.cursor() as cur:
                cur.execute(
                    """UPDATE sessions SET routing_key = %s
                       WHERE routing_key = 'p2p:web_user'""",
                    (target_routing_key,),
                )
                updated_sessions = cur.rowcount
                cur.execute(
                    "UPDATE conversations SET routing_key = %s WHERE routing_key = 'p2p:web_user'",
                    (target_routing_key,),
                )
                updated_convos = cur.rowcount
                cur.execute(
                    "UPDATE memories SET routing_key = %s WHERE routing_key = 'p2p:web_user'",
                    (target_routing_key,),
                )
                updated_mems = cur.rowcount
            self._conn.commit()
            total = updated_sessions + updated_convos + updated_mems
            if total:
                logger.info(
                    "PGStore: migrated legacy routing_keys from p2p:web_user to %s "
                    "(sessions=%d, conversations=%d, memories=%d)",
                    target_routing_key, updated_sessions, updated_convos, updated_mems,
                )
        except psycopg2.Error as exc:
            self._conn.rollback()
            logger.warning("PGStore: migrate_legacy_routing_keys failed: %s", exc)

    def backfill_session_org_ids(self, routing_key_to_org: dict[str, int]) -> int:
        """Backfill sessions.org_id from a {routing_key: org_id} map.

        Only updates rows where org_id IS NULL (never overwrites). Returns the
        total updated row count. Runs once at startup; silently degrades to 0
        if PG is unavailable.
        """
        if not routing_key_to_org or not self._ensure_connection():
            return 0
        updated = 0
        try:
            import psycopg2
            with self._conn.cursor() as cur:
                for routing_key, org_id in routing_key_to_org.items():
                    cur.execute(
                        "UPDATE sessions SET org_id = %s "
                        "WHERE routing_key = %s AND org_id IS NULL",
                        (org_id, routing_key),
                    )
                    updated += cur.rowcount
            self._conn.commit()
            if updated:
                logger.info("PGStore: backfilled org_id on %d sessions", updated)
        except psycopg2.Error as exc:
            self._conn.rollback()
            logger.warning("PGStore: backfill_session_org_ids failed: %s", exc)
            return 0
        return updated

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


def migrate_jsonl_sessions(pg_store: PGStore, session_mgr) -> tuple[int, int]:
    """One-shot, idempotent JSONL -> PostgreSQL session migration.

    The frontend serves the sessions list PG-first, so sessions created
    before PostgreSQL was enabled (JSONL only) silently disappear from the
    UI once PG comes online. This copies every indexed session missing from
    the ``sessions`` table -- together with its JSONL message history --
    into PG. Existing rows are never touched (ON CONFLICT DO NOTHING), so
    running it on every startup is safe.

    Returns ``(migrated_sessions, migrated_messages)``.
    """
    if not pg_store or not pg_store._ensure_connection():
        return 0, 0

    sessions_dir = session_mgr._sessions_dir
    migrated_sessions = 0
    migrated_messages = 0
    try:
        import psycopg2
        with pg_store._conn.cursor() as cur:
            # Lightweight in-place upgrade for databases created before the
            # task-status column existed (schema.sql ships it for new ones).
            cur.execute(
                "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS "
                "status TEXT NOT NULL DEFAULT 'completed'"
            )
            cur.execute("SELECT id FROM sessions")
            existing = {row[0] for row in cur.fetchall()}

            for s in session_mgr.list_all_sessions():
                if s["id"] in existing:
                    continue
                jsonl_path = sessions_dir / f"{s['id']}.jsonl"
                if not jsonl_path.exists() and not s.get("message_count"):
                    continue  # empty draft session, nothing to migrate

                cur.execute(
                    """INSERT INTO sessions
                           (id, routing_key, title, message_count, created_at, updated_at)
                       VALUES (%s, %s, %s, %s,
                               COALESCE(%s::timestamptz, NOW()),
                               COALESCE(%s::timestamptz, NOW()))
                       ON CONFLICT (id) DO NOTHING""",
                    (
                        s["id"], s["routing_key"], s.get("title") or "",
                        s.get("message_count") or 0,
                        s.get("updated_at") or None, s.get("updated_at") or None,
                    ),
                )
                migrated_sessions += cur.rowcount

                if not jsonl_path.exists():
                    continue
                for idx, line in enumerate(
                    jsonl_path.read_text(encoding="utf-8").splitlines()
                ):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if "role" not in entry:
                        continue
                    # +idx ms keeps intra-session ordering stable: user and
                    # assistant entries of one turn share the same ts, and
                    # fetch_conversations orders by created_at only.
                    ts = entry.get("ts") or 0
                    cur.execute(
                        """INSERT INTO conversations
                               (id, session_id, routing_key, role, content, created_at)
                           VALUES (%s, %s, %s, %s, %s,
                                   COALESCE(to_timestamp(%s / 1000.0), NOW()))
                           ON CONFLICT (id) DO NOTHING""",
                        (
                            f"{s['id']}_jsonl_{idx:04d}", s["id"],
                            s["routing_key"], entry.get("role", ""),
                            entry.get("content", ""),
                            (ts + idx) if ts else None,
                        ),
                    )
                    migrated_messages += cur.rowcount
        pg_store._conn.commit()
    except psycopg2.Error as exc:
        pg_store._conn.rollback()
        logger.warning("PGStore: JSONL session migration failed: %s", exc)
        return migrated_sessions, migrated_messages
    if migrated_sessions or migrated_messages:
        logger.info(
            "PGStore: migrated %d JSONL sessions (%d messages) into PostgreSQL",
            migrated_sessions, migrated_messages,
        )
    return migrated_sessions, migrated_messages

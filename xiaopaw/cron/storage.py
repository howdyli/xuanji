"""Cron/automation task storage — SQLite backend with JSON migration support."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from xiaopaw.cron.models import CronJob

logger = logging.getLogger(__name__)

_TABLE = "automation_tasks"

_COLUMNS = [
    "id",
    "name",
    "routing_key",
    "cron_expr",
    "content",
    "enabled",
    "description",
    "action_type",
    "skill_name",
    "last_run_at",
    "last_status",
    "fail_count",
    "max_retries",
    "created_at",
    "updated_at",
]

_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL DEFAULT '',
    routing_key   TEXT NOT NULL DEFAULT 'p2p:web_user',
    cron_expr     TEXT NOT NULL,
    content       TEXT NOT NULL DEFAULT '',
    enabled       INTEGER NOT NULL DEFAULT 1,
    description   TEXT NOT NULL DEFAULT '',
    action_type   TEXT NOT NULL DEFAULT 'dispatch',
    skill_name    TEXT NOT NULL DEFAULT '',
    last_run_at   TEXT NOT NULL DEFAULT '',
    last_status   TEXT NOT NULL DEFAULT '',
    fail_count    INTEGER NOT NULL DEFAULT 0,
    max_retries   INTEGER NOT NULL DEFAULT 3,
    created_at    TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT ''
)
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    return d


def _dict_to_job(d: dict) -> CronJob:
    """Safely build a CronJob, ignoring unknown keys."""
    known = {f for f in CronJob.model_fields}
    filtered = {k: v for k, v in d.items() if k in known}
    return CronJob(**filtered)


class CronStorage:
    """SQLite-backed storage for automation tasks.

    Parameters
    ----------
    db_path : Path
        Path to the SQLite database file (shared with auth/expert).
    filelock_timeout : float
        Unused (kept for API compatibility); SQLite handles its own locking.
    """

    def __init__(self, db_path: Path, *, data_dir: Path | None = None, filelock_timeout: float = 10.0) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        # Attempt migration from legacy JSON if data_dir provided
        if data_dir is not None:
            self._migrate_legacy(data_dir)

    # ── connection helpers ──────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(_CREATE_SQL)

    # ── legacy JSON migration ───────────────────────────────────────────

    def _migrate_legacy(self, data_dir: Path) -> None:
        tasks_path = data_dir / "cron" / "tasks.json"
        if not tasks_path.exists():
            return
        try:
            raw = json.loads(tasks_path.read_text(encoding="utf-8"))
            if not raw:
                return
            migrated = 0
            for item in raw:
                job = _dict_to_job(item)
                if self.get(job.id) is None:
                    self._insert(job)
                    migrated += 1
            if migrated:
                logger.info("automation: migrated %d tasks from legacy JSON", migrated)
            # Archive old file
            archive = tasks_path.with_suffix(".json.migrated")
            tasks_path.rename(archive)
            logger.info("automation: archived legacy file → %s", archive.name)
        except Exception:
            logger.exception("automation: JSON migration failed")

    # ── CRUD ────────────────────────────────────────────────────────────

    def load_all(self) -> list[CronJob]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM {_TABLE} ORDER BY created_at DESC"
            ).fetchall()
            return [_dict_to_job(_row_to_dict(r)) for r in rows]

    def get(self, task_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE id = ?", (task_id,)
            ).fetchone()
            return _row_to_dict(row) if row else None

    def create(self, data: dict) -> dict:
        now = _now_iso()
        task_id = data.get("id") or uuid.uuid4().hex[:12]
        job = _dict_to_job({
            "id": task_id,
            "name": data.get("name", ""),
            "routing_key": data.get("routing_key", "p2p:web_user"),
            "cron_expr": data.get("cron_expr", ""),
            "content": data.get("content", ""),
            "enabled": data.get("enabled", True),
            "description": data.get("description", ""),
            "action_type": data.get("action_type", "dispatch"),
            "skill_name": data.get("skill_name", ""),
            "fail_count": 0,
            "max_retries": data.get("max_retries", 3),
            "created_at": now,
            "updated_at": now,
        })
        self._insert(job)
        return self.get(task_id) or {}

    def update(self, task_id: str, data: dict) -> dict | None:
        existing = self.get(task_id)
        if not existing:
            return None
        allowed = {
            "name", "routing_key", "cron_expr", "content", "enabled",
            "description", "action_type", "skill_name", "max_retries",
        }
        sets = []
        vals = []
        for k in allowed:
            if k in data:
                sets.append(f"{k} = ?")
                v = data[k]
                if k == "enabled":
                    v = int(bool(v))
                vals.append(v)
        if not sets:
            return existing
        sets.append("updated_at = ?")
        vals.append(_now_iso())
        vals.append(task_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE {_TABLE} SET {', '.join(sets)} WHERE id = ?", vals
            )
        return self.get(task_id)

    def delete(self, task_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(f"DELETE FROM {_TABLE} WHERE id = ?", (task_id,))
            return cur.rowcount > 0

    def toggle(self, task_id: str) -> dict | None:
        existing = self.get(task_id)
        if not existing:
            return None
        new_enabled = int(not existing["enabled"])
        with self._conn() as conn:
            conn.execute(
                f"UPDATE {_TABLE} SET enabled = ?, updated_at = ? WHERE id = ?",
                (new_enabled, _now_iso(), task_id),
            )
        return self.get(task_id)

    def update_run_status(self, task_id: str, status: str, *, increment_fail: bool = False) -> None:
        now = _now_iso()
        if increment_fail:
            with self._conn() as conn:
                conn.execute(
                    f"UPDATE {_TABLE} SET last_run_at = ?, last_status = ?, "
                    f"fail_count = fail_count + 1, updated_at = ? WHERE id = ?",
                    (now, status, now, task_id),
                )
        else:
            with self._conn() as conn:
                conn.execute(
                    f"UPDATE {_TABLE} SET last_run_at = ?, last_status = ?, "
                    f"updated_at = ? WHERE id = ?",
                    (now, status, now, task_id),
                )

    def append_dlq(self, job: CronJob, error: str) -> None:
        """Append a failed job to the DLQ log file (kept for compatibility)."""
        dlq_path = self._db_path.parent / "automation.dlq.jsonl"
        entry = {"job": job.model_dump(), "error": error, "ts": _now_iso()}
        with dlq_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── internal ────────────────────────────────────────────────────────

    def _insert(self, job: CronJob) -> None:
        d = job.model_dump()
        d["enabled"] = int(bool(d["enabled"]))
        cols = ", ".join(_COLUMNS)
        placeholders = ", ".join("?" for _ in _COLUMNS)
        vals = [d.get(c, "") for c in _COLUMNS]
        with self._conn() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {_TABLE} ({cols}) VALUES ({placeholders})",
                vals,
            )

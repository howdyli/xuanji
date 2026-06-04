"""SQLite-backed user authentication and session management."""

from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_SESSION_DAYS = 7
_PBKDF2_ITERATIONS = 100_000


class UserAuth:
    """Manages users and sessions in a SQLite database.

    Schema
    ------
    users(id, username, password_hash, created_at)
    sessions(id, user_id, token, expires_at, created_at)
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        self._init_default_admin()

    # ── schema ────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    token TEXT UNIQUE NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def _init_default_admin(self) -> None:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count == 0:
                pw_hash = self._hash_password("admin123")
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    ("admin", pw_hash, now),
                )
                logger.warning(
                    "auth: no users found — created default admin (username=admin, password=admin123). "
                    "Change the password immediately!"
                )

    # ── public API ────────────────────────────────────────────────────

    def register(self, username: str, password: str) -> tuple[str, dict]:
        """Register a new user. Returns (token, user_dict).

        Raises ValueError if username is taken or invalid.
        """
        username = username.strip()
        if not username or len(username) < 2 or len(username) > 20:
            raise ValueError("用户名需要 2-20 个字符")
        if len(password) < 6:
            raise ValueError("密码至少 6 个字符")

        pw_hash = self._hash_password(password)
        now = datetime.now(timezone.utc).isoformat()

        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (username, pw_hash, now),
                )
            except sqlite3.IntegrityError:
                raise ValueError("用户名已存在")

            user_id = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()[0]

        token = self._create_session(user_id)
        user = self.get_user(user_id)
        return token, user

    def login(self, username: str, password: str) -> tuple[str, dict]:
        """Login with username and password. Returns (token, user_dict).

        Raises ValueError if credentials are invalid.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, password_hash FROM users WHERE username = ?",
                (username.strip(),),
            ).fetchone()

        if not row:
            raise ValueError("用户名或密码错误")

        user_id, stored_hash = row
        if not self._verify_password(password, stored_hash):
            raise ValueError("用户名或密码错误")

        token = self._create_session(user_id)
        user = self.get_user(user_id)
        return token, user

    def logout(self, token: str) -> None:
        """Delete a session token."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def validate_token(self, token: str) -> int | None:
        """Validate a session token. Returns user_id or None."""
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token = ?",
                (token,),
            ).fetchone()
        if not row:
            return None

        user_id, expires_at = row
        try:
            exp = datetime.fromisoformat(expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                # Session expired — clean up
                self.logout(token)
                return None
        except (ValueError, TypeError):
            return None

        return user_id

    def get_user(self, user_id: int) -> dict | None:
        """Get user info by id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return {"id": row[0], "username": row[1], "created_at": row[2]}

    def get_user_by_token(self, token: str) -> dict | None:
        """Get user info from a valid session token."""
        user_id = self.validate_token(token)
        if user_id is None:
            return None
        return self.get_user(user_id)

    def update_username(self, user_id: int, new_username: str) -> dict | None:
        """Update a user's username.

        Returns the updated user dict, or raises ValueError.
        """
        new_username = new_username.strip()
        if not new_username or len(new_username) < 2 or len(new_username) > 20:
            raise ValueError("用户名需要 2-20 个字符")

        with self._lock, self._connect() as conn:
            # Check uniqueness
            existing = conn.execute(
                "SELECT id FROM users WHERE username = ? AND id != ?",
                (new_username, user_id),
            ).fetchone()
            if existing:
                raise ValueError("用户名已被使用")

            conn.execute(
                "UPDATE users SET username = ? WHERE id = ?",
                (new_username, user_id),
            )

        return self.get_user(user_id)

    def change_password(self, user_id: int, old_password: str, new_password: str) -> bool:
        """Change a user's password.

        Returns True on success, raises ValueError on failure.
        """
        if len(new_password) < 6:
            raise ValueError("新密码至少 6 个字符")

        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()

        if not row:
            raise ValueError("用户不存在")

        if not self._verify_password(old_password, row[0]):
            raise ValueError("当前密码不正确")

        new_hash = self._hash_password(new_password)
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (new_hash, user_id),
            )
        return True

    # ── password hashing ──────────────────────────────────────────────

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
        )
        return f"{salt}:{h.hex()}"

    @staticmethod
    def _verify_password(password: str, stored: str) -> bool:
        try:
            salt, expected_hex = stored.split(":", 1)
            h = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
            )
            return secrets.compare_digest(h.hex(), expected_hex)
        except (ValueError, AttributeError):
            return False

    # ── session management ────────────────────────────────────────────

    def _create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=_SESSION_DAYS)

        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (user_id, token, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (user_id, token, expires.isoformat(), now.isoformat()),
            )
        return token

    # ── DB helper ─────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

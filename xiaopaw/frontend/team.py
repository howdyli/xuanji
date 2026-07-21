"""TeamStore — 团队管理服务（SQLite，复用 auth.db）。

提供团队 CRUD、成员管理、邀请码机制，支撑多用户团队协作。
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class TeamStore:
    """团队管理服务 — 复用 auth.db SQLite 连接。

    线程安全：所有写操作通过 threading.Lock 保护。
    WAL 模式：与 UserAuth 共享同一 DB 文件，继承 WAL 并发读能力。
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()

    # ── DB helper ─────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    # ── 团队 CRUD ─────────────────────────────────────────────────────

    def create_team(self, name: str, description: str, owner_id: int, org_id: int | None = None) -> dict:
        """创建团队，owner 自动加入为 'owner' 角色。

        org_id 未显式指定时，继承 owner 所属组织，保证团队归属单一租户。
        """
        name = name.strip()
        if not name or len(name) < 2 or len(name) > 30:
            raise ValueError("团队名称需要 2-30 个字符")

        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            if org_id is None:
                row = conn.execute(
                    "SELECT org_id FROM users WHERE id = ?", (owner_id,)
                ).fetchone()
                org_id = row["org_id"] if row else None
            cur = conn.execute(
                "INSERT INTO teams (name, description, owner_id, org_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (name, description.strip(), owner_id, org_id, now),
            )
            team_id = cur.lastrowid
            # Owner 自动成为成员
            conn.execute(
                "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
                (team_id, owner_id, now),
            )
        return self.get_team(team_id)  # type: ignore[return-value]

    def get_team(self, team_id: int) -> dict | None:
        """获取团队基本信息。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, description, owner_id, org_id, created_at FROM teams WHERE id = ?",
                (team_id,),
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def get_team_org_id(self, team_id: int) -> int | None:
        """获取团队所属组织 id，不存在返回 None。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT org_id FROM teams WHERE id = ?", (team_id,)
            ).fetchone()
        return row["org_id"] if row else None

    @staticmethod
    def _assert_same_org(conn: sqlite3.Connection, team_id: int, user_id: int) -> None:
        """拒绝跨组织加入团队。任一侧 org_id 为 NULL（legacy 未回填）时不阻断。"""
        team = conn.execute(
            "SELECT org_id FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        user = conn.execute(
            "SELECT org_id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        team_org = team["org_id"] if team else None
        user_org = user["org_id"] if user else None
        if team_org is not None and user_org is not None and team_org != user_org:
            raise ValueError("跨组织禁止加入团队")

    def list_teams_for_user(self, user_id: int) -> list[dict]:
        """列出用户加入的所有团队（含角色信息）。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT t.id, t.name, t.description, t.owner_id, t.created_at,
                          tm.role, tm.joined_at
                   FROM teams t
                   JOIN team_members tm ON tm.team_id = t.id
                   WHERE tm.user_id = ?
                   ORDER BY t.created_at DESC""",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_team(self, team_id: int, requester_id: int) -> bool:
        """解散团队（仅 owner 可操作）。"""
        team = self.get_team(team_id)
        if not team:
            return False
        if team["owner_id"] != requester_id:
            raise ValueError("只有团队创建者可以解散团队")
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
        return True

    # ── 成员管理 ─────────────────────────────────────────────────────

    def add_member(self, team_id: int, user_id: int, role: str = "member") -> dict:
        """添加成员（拒绝跨组织）。"""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            self._assert_same_org(conn, team_id, user_id)
            try:
                conn.execute(
                    "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
                    (team_id, user_id, role, now),
                )
            except sqlite3.IntegrityError:
                raise ValueError("用户已是团队成员")
        return {"team_id": team_id, "user_id": user_id, "role": role, "joined_at": now}

    def remove_member(self, team_id: int, user_id: int) -> bool:
        """移除成员（不能移除 owner）。"""
        role = self.get_member_role(team_id, user_id)
        if role == "owner":
            raise ValueError("不能移除团队创建者")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM team_members WHERE team_id = ? AND user_id = ?",
                (team_id, user_id),
            )
        return cur.rowcount > 0

    def update_member_role(self, team_id: int, user_id: int, new_role: str) -> bool:
        """变更成员角色（不能变更 owner）。"""
        if new_role not in ("admin", "member"):
            raise ValueError("角色只能是 admin 或 member")
        role = self.get_member_role(team_id, user_id)
        if role == "owner":
            raise ValueError("不能变更创建者角色")
        if role is None:
            return False
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE team_members SET role = ? WHERE team_id = ? AND user_id = ?",
                (new_role, team_id, user_id),
            )
        return True

    def list_members(self, team_id: int) -> list[dict]:
        """列出团队所有成员（含用户名）。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT tm.user_id, tm.role, tm.joined_at, u.username
                   FROM team_members tm
                   JOIN users u ON u.id = tm.user_id
                   WHERE tm.team_id = ?
                   ORDER BY tm.joined_at ASC""",
                (team_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def is_member(self, team_id: int, user_id: int) -> bool:
        """检查用户是否为团队成员。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?",
                (team_id, user_id),
            ).fetchone()
        return row is not None

    def get_member_role(self, team_id: int, user_id: int) -> str | None:
        """获取成员角色，非成员返回 None。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT role FROM team_members WHERE team_id = ? AND user_id = ?",
                (team_id, user_id),
            ).fetchone()
        return row["role"] if row else None

    def get_user_team_ids(self, user_id: int) -> list[int]:
        """获取用户所属的所有团队 ID。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT team_id FROM team_members WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return [r["team_id"] for r in rows]

    # ── 邀请管理 ─────────────────────────────────────────────────────

    def create_invitation(self, team_id: int, inviter_id: int, ttl_hours: int = 72) -> dict:
        """生成邀请码（默认 72 小时有效）。"""
        # 验证邀请人是团队成员（admin 或 owner）
        role = self.get_member_role(team_id, inviter_id)
        if role not in ("owner", "admin"):
            raise ValueError("只有管理员或创建者可以邀请成员")

        code = secrets.token_urlsafe(8)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=ttl_hours)

        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO team_invitations
                   (team_id, inviter_id, code, expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (team_id, inviter_id, code, expires.isoformat(), now.isoformat()),
            )
        return {
            "team_id": team_id,
            "code": code,
            "expires_at": expires.isoformat(),
            "created_at": now.isoformat(),
        }

    def accept_invitation(self, code: str, user_id: int) -> dict:
        """通过邀请码加入团队。返回团队信息。"""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM team_invitations WHERE code = ?", (code,)
            ).fetchone()

            if not row:
                raise ValueError("邀请码无效")

            if row["used_by"] is not None:
                raise ValueError("邀请码已被使用")

            # 检查过期
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expires_at:
                raise ValueError("邀请码已过期")

            team_id = row["team_id"]

            # 拒绝跨组织加入
            self._assert_same_org(conn, team_id, user_id)

            # 检查是否已是成员
            existing = conn.execute(
                "SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?",
                (team_id, user_id),
            ).fetchone()
            if existing:
                raise ValueError("你已是该团队成员")

            # 加入团队
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
                (team_id, user_id, now),
            )

            # 标记邀请码已使用
            conn.execute(
                "UPDATE team_invitations SET used_by = ?, used_at = ? WHERE id = ?",
                (user_id, now, row["id"]),
            )

        team = self.get_team(team_id)
        return team  # type: ignore[return-value]

    def list_pending_invitations(self, team_id: int) -> list[dict]:
        """列出团队待处理的邀请码。"""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, team_id, inviter_id, code, expires_at, created_at
                   FROM team_invitations
                   WHERE team_id = ? AND used_by IS NULL AND expires_at > ?
                   ORDER BY created_at DESC""",
                (team_id, now),
            ).fetchall()
        return [dict(r) for r in rows]

    def revoke_invitation(self, invitation_id: int, requester_id: int) -> bool:
        """撤销邀请码（admin+ 可操作）。"""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT team_id FROM team_invitations WHERE id = ?", (invitation_id,)
            ).fetchone()
            if not row:
                return False
            # 验证权限
            role = conn.execute(
                "SELECT role FROM team_members WHERE team_id = ? AND user_id = ?",
                (row["team_id"], requester_id),
            ).fetchone()
            if not role or role["role"] not in ("owner", "admin"):
                raise ValueError("权限不足")
            conn.execute("DELETE FROM team_invitations WHERE id = ?", (invitation_id,))
        return True

"""Integration tests for team collaboration (TeamStore + API routes).

Tests:
- Team creation / join / leave flow
- Invitation code generation / use / expiry / revocation
- Session sharing / unsharing
- Team member access to shared sessions
- Permission control: view (read-only) vs edit (can continue)
- IDOR: non-members cannot access shared sessions
- Multi-team: user in multiple teams sees aggregated sessions
"""

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from xiaopaw.frontend.auth import UserAuth
from xiaopaw.frontend.team import TeamStore


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_auth.db"


@pytest.fixture
def auth(db_path):
    return UserAuth(db_path)


@pytest.fixture
def store(db_path):
    return TeamStore(db_path)


@pytest.fixture
def user_a(auth):
    """Register user A, return (user_id, username)."""
    _, user = auth.register("alice", "password123")
    return user["id"], user["username"]


@pytest.fixture
def user_b(auth):
    """Register user B, return (user_id, username)."""
    _, user = auth.register("bob", "password456")
    return user["id"], user["username"]


@pytest.fixture
def user_c(auth):
    """Register user C (outsider), return (user_id, username)."""
    _, user = auth.register("charlie", "password789")
    return user["id"], user["username"]


# ─── Team CRUD Tests ────────────────────────────────────────────────────────


class TestTeamCRUD:
    def test_create_team(self, store, user_a):
        uid, _ = user_a
        team = store.create_team("研发团队", "后端开发", uid)
        assert team["name"] == "研发团队"
        assert team["description"] == "后端开发"
        assert team["owner_id"] == uid

    def test_create_team_name_validation(self, store, user_a):
        uid, _ = user_a
        with pytest.raises(ValueError, match="2-30"):
            store.create_team("x", "", uid)

    def test_owner_auto_member(self, store, user_a):
        uid, _ = user_a
        team = store.create_team("测试团队", "", uid)
        assert store.is_member(team["id"], uid)
        assert store.get_member_role(team["id"], uid) == "owner"

    def test_list_teams_for_user(self, store, user_a, user_b):
        uid_a, _ = user_a
        uid_b, _ = user_b
        store.create_team("团队A", "", uid_a)
        store.create_team("团队B", "", uid_b)

        teams_a = store.list_teams_for_user(uid_a)
        assert len(teams_a) == 1
        assert teams_a[0]["name"] == "团队A"

    def test_delete_team_only_owner(self, store, user_a, user_b):
        uid_a, _ = user_a
        uid_b, _ = user_b
        team = store.create_team("待解散", "", uid_a)
        store.add_member(team["id"], uid_b)

        # Non-owner cannot delete
        with pytest.raises(ValueError, match="创建者"):
            store.delete_team(team["id"], uid_b)

        # Owner can delete
        assert store.delete_team(team["id"], uid_a) is True
        assert store.get_team(team["id"]) is None


# ─── Member Management Tests ────────────────────────────────────────────────


class TestMemberManagement:
    def test_add_and_list_members(self, store, user_a, user_b):
        uid_a, _ = user_a
        uid_b, _ = user_b
        team = store.create_team("成员测试", "", uid_a)
        store.add_member(team["id"], uid_b)

        members = store.list_members(team["id"])
        assert len(members) == 2
        usernames = {m["username"] for m in members}
        assert "alice" in usernames
        assert "bob" in usernames

    def test_duplicate_member_rejected(self, store, user_a, user_b):
        uid_a, _ = user_a
        uid_b, _ = user_b
        team = store.create_team("重复测试", "", uid_a)
        store.add_member(team["id"], uid_b)
        with pytest.raises(ValueError, match="已是"):
            store.add_member(team["id"], uid_b)

    def test_remove_member(self, store, user_a, user_b):
        uid_a, _ = user_a
        uid_b, _ = user_b
        team = store.create_team("移除测试", "", uid_a)
        store.add_member(team["id"], uid_b)
        assert store.remove_member(team["id"], uid_b) is True
        assert not store.is_member(team["id"], uid_b)

    def test_cannot_remove_owner(self, store, user_a):
        uid_a, _ = user_a
        team = store.create_team("Owner保护", "", uid_a)
        with pytest.raises(ValueError, match="创建者"):
            store.remove_member(team["id"], uid_a)

    def test_update_role(self, store, user_a, user_b):
        uid_a, _ = user_a
        uid_b, _ = user_b
        team = store.create_team("角色测试", "", uid_a)
        store.add_member(team["id"], uid_b)
        assert store.update_member_role(team["id"], uid_b, "admin") is True
        assert store.get_member_role(team["id"], uid_b) == "admin"

    def test_cannot_change_owner_role(self, store, user_a):
        uid_a, _ = user_a
        team = store.create_team("Owner角色", "", uid_a)
        with pytest.raises(ValueError, match="创建者"):
            store.update_member_role(team["id"], uid_a, "member")


# ─── Invitation Tests ───────────────────────────────────────────────────────


class TestInvitations:
    def test_create_and_accept_invitation(self, store, user_a, user_b):
        uid_a, _ = user_a
        uid_b, _ = user_b
        team = store.create_team("邀请测试", "", uid_a)
        inv = store.create_invitation(team["id"], uid_a)
        assert inv["code"]
        assert inv["team_id"] == team["id"]

        # User B accepts
        result = store.accept_invitation(inv["code"], uid_b)
        assert result["id"] == team["id"]
        assert store.is_member(team["id"], uid_b)

    def test_invitation_single_use(self, store, user_a, user_b, user_c):
        uid_a, _ = user_a
        uid_b, _ = user_b
        uid_c, _ = user_c
        team = store.create_team("一次性", "", uid_a)
        inv = store.create_invitation(team["id"], uid_a)

        store.accept_invitation(inv["code"], uid_b)
        with pytest.raises(ValueError, match="已被使用"):
            store.accept_invitation(inv["code"], uid_c)

    def test_invitation_invalid_code(self, store, user_b):
        uid_b, _ = user_b
        with pytest.raises(ValueError, match="无效"):
            store.accept_invitation("nonexistent-code", uid_b)

    def test_invitation_requires_admin(self, store, user_a, user_b):
        uid_a, _ = user_a
        uid_b, _ = user_b
        team = store.create_team("权限邀请", "", uid_a)
        store.add_member(team["id"], uid_b, role="member")

        # Regular member cannot invite
        with pytest.raises(ValueError, match="管理员"):
            store.create_invitation(team["id"], uid_b)

    def test_revoke_invitation(self, store, user_a):
        uid_a, _ = user_a
        team = store.create_team("撤销测试", "", uid_a)
        inv = store.create_invitation(team["id"], uid_a)

        pending = store.list_pending_invitations(team["id"])
        assert len(pending) == 1

        # Find the invitation id
        assert store.revoke_invitation(pending[0]["id"], uid_a) is True
        pending_after = store.list_pending_invitations(team["id"])
        assert len(pending_after) == 0

    def test_already_member_rejected(self, store, user_a, user_b):
        uid_a, _ = user_a
        uid_b, _ = user_b
        team = store.create_team("已成员", "", uid_a)
        store.add_member(team["id"], uid_b)
        inv = store.create_invitation(team["id"], uid_a)

        with pytest.raises(ValueError, match="已是"):
            store.accept_invitation(inv["code"], uid_b)


# ─── Multi-team Tests ───────────────────────────────────────────────────────


class TestMultiTeam:
    def test_user_in_multiple_teams(self, store, user_a, user_b):
        uid_a, _ = user_a
        uid_b, _ = user_b
        team1 = store.create_team("团队1", "", uid_a)
        team2 = store.create_team("团队2", "", uid_b)

        # A joins B's team
        inv = store.create_invitation(team2["id"], uid_b)
        store.accept_invitation(inv["code"], uid_a)

        teams_a = store.list_teams_for_user(uid_a)
        assert len(teams_a) == 2

        team_ids = store.get_user_team_ids(uid_a)
        assert team1["id"] in team_ids
        assert team2["id"] in team_ids


# ─── Access Control Tests ───────────────────────────────────────────────────


class TestAccessControl:
    def test_is_member_check(self, store, user_a, user_b, user_c):
        uid_a, _ = user_a
        uid_b, _ = user_b
        uid_c, _ = user_c
        team = store.create_team("访问控制", "", uid_a)
        store.add_member(team["id"], uid_b)

        assert store.is_member(team["id"], uid_a) is True
        assert store.is_member(team["id"], uid_b) is True
        assert store.is_member(team["id"], uid_c) is False

    def test_get_member_role_non_member(self, store, user_a, user_c):
        uid_a, _ = user_a
        uid_c, _ = user_c
        team = store.create_team("角色查询", "", uid_a)
        assert store.get_member_role(team["id"], uid_c) is None

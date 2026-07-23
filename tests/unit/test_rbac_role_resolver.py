"""Unit tests for RBAC role resolution (F2 wiring).

Covers:
1. UserAuth.get_user_by_username lookups.
2. resolve_rbac_role mapping policy (admin/member/"" + failure degradation).
3. Runner.set_role_resolver install/clear semantics.
"""

from __future__ import annotations

import pytest

from xiaopaw.frontend.auth import UserAuth
from xiaopaw.frontend.rbac import resolve_rbac_role


@pytest.fixture
def auth(tmp_path):
    # UserAuth bootstraps a default admin (username="admin", is_admin=1).
    return UserAuth(tmp_path / "auth.db")


# ─── get_user_by_username ────────────────────────────────────────────────


def test_get_user_by_username_admin(auth):
    admin = auth.get_user_by_username("admin")
    assert admin is not None
    assert admin["username"] == "admin"
    assert admin["is_admin"] is True


def test_get_user_by_username_regular(auth):
    auth.register("alice", "password123")
    alice = auth.get_user_by_username("alice")
    assert alice is not None
    assert alice["is_admin"] is False
    assert alice["org_id"] == auth.get_default_org_id()


def test_get_user_by_username_missing(auth):
    assert auth.get_user_by_username("nobody") is None


def test_get_user_by_username_empty(auth):
    assert auth.get_user_by_username("") is None


# ─── resolve_rbac_role mapping ───────────────────────────────────────────


def test_resolve_role_admin(auth):
    assert resolve_rbac_role(auth, "admin") == "admin"


def test_resolve_role_member(auth):
    auth.register("bob", "password123")
    assert resolve_rbac_role(auth, "bob") == "member"


@pytest.mark.parametrize("sender", ["", "cron", "anonymous", "  ", "ghost_open_id"])
def test_resolve_role_non_user_senders(auth, sender):
    """System actors, blanks and unknown feishu open_ids get no role."""
    assert resolve_rbac_role(auth, sender) == ""


def test_resolve_role_degrades_on_error():
    """A broken user store never raises; it degrades to no role."""

    class Broken:
        def get_user_by_username(self, _username):
            raise RuntimeError("db down")

    assert resolve_rbac_role(Broken(), "alice") == ""


def test_resolve_role_strips_whitespace(auth):
    assert resolve_rbac_role(auth, "  admin  ") == "admin"


# ─── Runner.set_role_resolver ────────────────────────────────────────────


def _make_runner():
    from xiaopaw.runner import Runner

    # Runner only stores collaborators; no async setup needed for this test.
    return Runner(
        session_mgr=object(),
        sender=object(),
        agent_fn=lambda *a, **k: None,
    )


def test_runner_default_has_no_resolver():
    runner = _make_runner()
    assert runner._role_resolver is None


def test_runner_set_and_clear_resolver():
    runner = _make_runner()
    resolver = lambda inbound: "admin"  # noqa: E731
    runner.set_role_resolver(resolver)
    assert runner._role_resolver is resolver
    runner.set_role_resolver(None)
    assert runner._role_resolver is None

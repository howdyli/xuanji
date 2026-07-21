"""Integration tests for shared-session view/edit permission enforcement.

The write path (POST /api/frontend/message) must enforce team share
permissions when a caller targets a session owned by a *different*
routing_key (i.e. a team-shared session):

- ``edit`` share  -> write allowed (reaches the runner)
- ``view`` share  -> read-only, write rejected with 403
- no team access  -> hidden with 404 (prevents session hijacking, since
  ``activate_session`` would otherwise adopt the session into the caller)
- own session     -> no share check performed at all

These tests drive the aiohttp handler with a real ``UserAuth`` (for token
auth) and lightweight fakes for the runner / session manager, and monkeypatch
the PG-backed permission resolver so no PostgreSQL is required.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from xiaopaw.frontend.auth import UserAuth
from xiaopaw.frontend.routes import session as session_routes
from xiaopaw.frontend.routes.session import register_session_routes

SHARED_SID = "s-shared-0001"
FOREIGN_RK = "p2p:web_bob"


class _FakeSessionMgr:
    """Minimal SessionManager stand-in for the message handler.

    The hinted session is owned by ``FOREIGN_RK`` so the handler treats it as
    a team-shared session and consults the permission resolver.
    """

    def __init__(self) -> None:
        self._index = {
            FOREIGN_RK: SimpleNamespace(
                active_session_id=SHARED_SID,
                sessions=[SimpleNamespace(id=SHARED_SID)],
            )
        }
        self.activate_session = AsyncMock(return_value=SimpleNamespace(id=SHARED_SID))

    async def get_session_by_id(self, session_id: str):
        for entry in self._index.values():
            for s in entry.sessions:
                if s.id == session_id:
                    return s
        return None

    async def get_or_create(self, routing_key: str):
        return SimpleNamespace(id=SHARED_SID, message_count=0)


@pytest.fixture
def app_and_token(tmp_path):
    """aiohttp app with real UserAuth (alice) + fake runner/session manager."""
    auth = UserAuth(tmp_path / "auth.db")  # bootstraps default admin
    alice_token, _ = auth.register("alice", "password123")

    app = web.Application()
    app["user_auth"] = auth
    app["session_mgr"] = _FakeSessionMgr()
    app["runner"] = SimpleNamespace(dispatch=AsyncMock())
    # A plain (non-CaptureSender) sender: no reply future is registered.
    app["sender"] = SimpleNamespace()
    app["pg_store"] = None
    register_session_routes(app)
    return app, alice_token


async def _post_message(client: TestClient, token: str) -> web.Response:
    return await client.post(
        "/api/frontend/message",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "继续处理这个任务", "session_id": SHARED_SID},
    )


async def test_write_to_view_shared_session_forbidden(app_and_token, monkeypatch):
    """A ``view``-only shared session rejects writes with 403."""
    app, token = app_and_token
    monkeypatch.setattr(
        session_routes, "_resolve_shared_session_permission", lambda req, sid: "view"
    )
    async with TestClient(TestServer(app)) as client:
        r = await _post_message(client, token)
        assert r.status == 403
        # The runner must never be reached for a rejected write.
        app["runner"].dispatch.assert_not_called()


async def test_write_to_unauthorized_session_not_found(app_and_token, monkeypatch):
    """No team-shared access -> 404 (session stays hidden, no hijack)."""
    app, token = app_and_token
    monkeypatch.setattr(
        session_routes, "_resolve_shared_session_permission", lambda req, sid: None
    )
    async with TestClient(TestServer(app)) as client:
        r = await _post_message(client, token)
        assert r.status == 404
        app["runner"].dispatch.assert_not_called()
        app["session_mgr"].activate_session.assert_not_called()


async def test_write_to_edit_shared_session_allowed(app_and_token, monkeypatch):
    """An ``edit`` share allows the write to proceed to the runner."""
    app, token = app_and_token
    monkeypatch.setattr(
        session_routes, "_resolve_shared_session_permission", lambda req, sid: "edit"
    )
    async with TestClient(TestServer(app)) as client:
        r = await _post_message(client, token)
        assert r.status == 200
        app["runner"].dispatch.assert_called_once()
        app["session_mgr"].activate_session.assert_awaited_once()


async def test_write_to_own_session_skips_share_check(app_and_token, monkeypatch):
    """Writing to a session the caller owns performs no share-permission check."""
    app, token = app_and_token
    # Re-own the hinted session under alice's routing_key.
    app["session_mgr"]._index = {
        "p2p:web_alice": SimpleNamespace(
            active_session_id=SHARED_SID,
            sessions=[SimpleNamespace(id=SHARED_SID)],
        )
    }

    called = {"n": 0}

    def _tripwire(req, sid):  # pragma: no cover - must not be invoked
        called["n"] += 1
        return "view"

    monkeypatch.setattr(
        session_routes, "_resolve_shared_session_permission", _tripwire
    )
    async with TestClient(TestServer(app)) as client:
        r = await _post_message(client, token)
        assert r.status == 200
        assert called["n"] == 0
        app["runner"].dispatch.assert_called_once()

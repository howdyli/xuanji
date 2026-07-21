"""Integration tests for notification API routes (mocked store, real UserAuth)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from xiaopaw.frontend.auth import UserAuth
from xiaopaw.frontend.routes.notifications import register_notification_routes


@pytest.fixture
def notif_app(tmp_path):
    """aiohttp app with real UserAuth (alice) and a mocked notification store."""
    auth = UserAuth(tmp_path / "auth.db")  # bootstraps default admin
    alice_token, _ = auth.register("alice", "password123")

    app = web.Application()
    app["user_auth"] = auth
    store = MagicMock()
    store.list.return_value = {"notifications": [], "total": 0}
    store.unread_count.return_value = 3
    store.mark_read.return_value = True
    store.mark_all_read.return_value = 2
    app["notification_store"] = store
    register_notification_routes(app)
    return app, alice_token, store


@pytest.mark.asyncio
async def test_list_requires_auth(notif_app):
    app, _, _ = notif_app
    async with TestClient(TestServer(app)) as client:
        r = await client.get("/api/frontend/notifications")
        assert r.status == 401


@pytest.mark.asyncio
async def test_service_unavailable_returns_503(tmp_path):
    auth = UserAuth(tmp_path / "auth.db")
    token, _ = auth.register("alice", "password123")
    app = web.Application()
    app["user_auth"] = auth
    app["notification_store"] = None  # not assembled
    register_notification_routes(app)
    async with TestClient(TestServer(app)) as client:
        r = await client.get(
            "/api/frontend/notifications",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status == 503


@pytest.mark.asyncio
async def test_list_forces_recipient_to_current_user(notif_app):
    app, token, store = notif_app
    async with TestClient(TestServer(app)) as client:
        r = await client.get(
            "/api/frontend/notifications?unread_only=true&page=2&page_size=5",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status == 200
        store.list.assert_called_once_with(
            "alice", unread_only=True, page=2, page_size=5
        )


@pytest.mark.asyncio
async def test_unread_count(notif_app):
    app, token, store = notif_app
    async with TestClient(TestServer(app)) as client:
        r = await client.get(
            "/api/frontend/notifications/unread-count",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status == 200
        assert (await r.json())["count"] == 3
        store.unread_count.assert_called_once_with("alice")


@pytest.mark.asyncio
async def test_mark_read_forces_recipient(notif_app):
    app, token, store = notif_app
    async with TestClient(TestServer(app)) as client:
        r = await client.post(
            "/api/frontend/notifications/42/read",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status == 200
        store.mark_read.assert_called_once_with(42, "alice")


@pytest.mark.asyncio
async def test_mark_read_others_notification_404(notif_app):
    app, token, store = notif_app
    store.mark_read.return_value = False  # recipient mismatch
    async with TestClient(TestServer(app)) as client:
        r = await client.post(
            "/api/frontend/notifications/99/read",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status == 404


@pytest.mark.asyncio
async def test_mark_all_read(notif_app):
    app, token, store = notif_app
    async with TestClient(TestServer(app)) as client:
        r = await client.post(
            "/api/frontend/notifications/read-all",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status == 200
        assert (await r.json())["updated"] == 2
        store.mark_all_read.assert_called_once_with("alice")

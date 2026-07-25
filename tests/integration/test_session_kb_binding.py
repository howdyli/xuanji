"""Integration tests for session ↔ knowledge-base binding endpoints.

GET/PUT /api/frontend/sessions/{sid}/knowledge-bases must enforce:

- auth gate                 -> 401 without a token
- session IDOR              -> unknown / foreign non-shared sessions are 404
- shared-session writes     -> ``view`` share is read-only (PUT 403), ``edit`` allowed
- base readability (PUT)    -> any unreadable kb_id rejects the whole PUT with 403
- binding cap (PUT)         -> more than 5 bases -> 422; malformed body -> 422
- GET hygiene               -> deleted / unreadable bases silently dropped

Mirrors the TestServer/TestClient harness of test_session_share_permission.py:
real UserAuth for tokens, fake session manager, and a monkeypatched
knowledge-store factory so no PostgreSQL is required.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import xiaopaw.frontend.routes.knowledge as kb_routes
from xiaopaw.frontend.auth import UserAuth
from xiaopaw.frontend.routes import session as session_routes
from xiaopaw.frontend.routes.session import register_session_routes

OWN_SID = "s-own-0001"
FOREIGN_SID = "s-foreign-0001"
ALICE_RK = "p2p:web_alice"
FOREIGN_RK = "p2p:web_bob"


class _FakeSessionMgr:
    """alice owns OWN_SID; bob owns FOREIGN_SID (candidate for team sharing)."""

    def __init__(self) -> None:
        self._index = {
            ALICE_RK: SimpleNamespace(
                active_session_id=OWN_SID, sessions=[SimpleNamespace(id=OWN_SID)]
            ),
            FOREIGN_RK: SimpleNamespace(
                active_session_id=FOREIGN_SID, sessions=[SimpleNamespace(id=FOREIGN_SID)]
            ),
        }

    async def get_session_by_id(self, session_id: str):
        for entry in self._index.values():
            for s in entry.sessions:
                if s.id == session_id:
                    return s
        return None


class _FakeKbStore:
    """In-memory bases + session bindings; mirrors the KnowledgeStore surface used."""

    def __init__(self) -> None:
        self.bases: dict[str, dict] = {}
        self.bindings: dict[str, list[str]] = {}

    def add_personal_base(self, kb_id: str, owner_key: str, name: str = "库") -> None:
        self.bases[kb_id] = {
            "id": kb_id, "name": name, "scope": "personal",
            "owner_key": owner_key, "org_id": None,
        }

    def get_base(self, kb_id: str):
        return self.bases.get(kb_id)

    def get_session_bases(self, session_id: str) -> list[str]:
        return self.bindings.get(session_id, [])

    def set_session_bases(self, session_id: str, kb_ids: list[str]) -> None:
        self.bindings[session_id] = list(kb_ids)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """App + alice token + fake kb store (injected via _get_store)."""
    auth = UserAuth(tmp_path / "auth.db")
    alice_token, _ = auth.register("alice", "password123")

    app = web.Application()
    app["user_auth"] = auth
    app["session_mgr"] = _FakeSessionMgr()
    app["pg_store"] = None
    register_session_routes(app)

    kb_store = _FakeKbStore()
    kb_store.add_personal_base("kb-mine-1", ALICE_RK, "我的库一")
    kb_store.add_personal_base("kb-mine-2", ALICE_RK, "我的库二")
    kb_store.add_personal_base("kb-bob", FOREIGN_RK, "别人的库")
    monkeypatch.setattr(kb_routes, "_get_store", lambda request: kb_store)
    return app, alice_token, kb_store


def _url(sid: str) -> str:
    return f"/api/frontend/sessions/{sid}/knowledge-bases"


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_unauthorized_without_token(env):
    app, _token, _store = env
    async with TestClient(TestServer(app)) as client:
        assert (await client.get(_url(OWN_SID))).status == 401
        r = await client.put(_url(OWN_SID), json={"kb_ids": []})
        assert r.status == 401


async def test_put_then_get_roundtrip_on_own_session(env):
    app, token, store = env
    async with TestClient(TestServer(app)) as client:
        r = await client.put(
            _url(OWN_SID), headers=_hdr(token), json={"kb_ids": ["kb-mine-1", "kb-mine-2"]}
        )
        assert r.status == 200
        assert (await r.json())["kb_ids"] == ["kb-mine-1", "kb-mine-2"]
        assert store.bindings[OWN_SID] == ["kb-mine-1", "kb-mine-2"]

        r = await client.get(_url(OWN_SID), headers=_hdr(token))
        assert r.status == 200
        data = await r.json()
        assert data["kb_ids"] == ["kb-mine-1", "kb-mine-2"]
        assert [b["name"] for b in data["bases"]] == ["我的库一", "我的库二"]


async def test_put_empty_list_unbinds_all(env):
    app, token, store = env
    store.bindings[OWN_SID] = ["kb-mine-1"]
    async with TestClient(TestServer(app)) as client:
        r = await client.put(_url(OWN_SID), headers=_hdr(token), json={"kb_ids": []})
        assert r.status == 200
        assert store.bindings[OWN_SID] == []


async def test_put_unreadable_base_forbidden(env):
    app, token, store = env
    async with TestClient(TestServer(app)) as client:
        r = await client.put(
            _url(OWN_SID), headers=_hdr(token), json={"kb_ids": ["kb-mine-1", "kb-bob"]}
        )
        assert r.status == 403
        # Rejected as a whole: nothing was persisted.
        assert OWN_SID not in store.bindings


async def test_put_over_binding_cap_rejected(env):
    app, token, store = env
    for i in range(6):
        store.add_personal_base(f"kb-x{i}", ALICE_RK)
    async with TestClient(TestServer(app)) as client:
        r = await client.put(
            _url(OWN_SID), headers=_hdr(token),
            json={"kb_ids": [f"kb-x{i}" for i in range(6)]},
        )
        assert r.status == 422


async def test_put_malformed_body_rejected(env):
    app, token, _store = env
    async with TestClient(TestServer(app)) as client:
        for bad in ({"kb_ids": "kb-1"}, {"kb_ids": [1, 2]}, {}, {"kb_ids": [""]}):
            r = await client.put(_url(OWN_SID), headers=_hdr(token), json=bad)
            assert r.status == 422, bad


async def test_unknown_session_not_found(env):
    app, token, _store = env
    async with TestClient(TestServer(app)) as client:
        assert (await client.get(_url("s-nope"), headers=_hdr(token))).status == 404


async def test_foreign_session_without_share_hidden(env, monkeypatch):
    app, token, _store = env
    monkeypatch.setattr(
        session_routes, "_resolve_shared_session_permission", lambda req, sid: None
    )
    async with TestClient(TestServer(app)) as client:
        assert (await client.get(_url(FOREIGN_SID), headers=_hdr(token))).status == 404
        r = await client.put(_url(FOREIGN_SID), headers=_hdr(token), json={"kb_ids": []})
        assert r.status == 404


async def test_view_share_allows_get_but_rejects_put(env, monkeypatch):
    app, token, _store = env
    monkeypatch.setattr(
        session_routes, "_resolve_shared_session_permission", lambda req, sid: "view"
    )
    async with TestClient(TestServer(app)) as client:
        assert (await client.get(_url(FOREIGN_SID), headers=_hdr(token))).status == 200
        r = await client.put(_url(FOREIGN_SID), headers=_hdr(token), json={"kb_ids": []})
        assert r.status == 403


async def test_edit_share_allows_put(env, monkeypatch):
    app, token, store = env
    monkeypatch.setattr(
        session_routes, "_resolve_shared_session_permission", lambda req, sid: "edit"
    )
    async with TestClient(TestServer(app)) as client:
        r = await client.put(
            _url(FOREIGN_SID), headers=_hdr(token), json={"kb_ids": ["kb-mine-1"]}
        )
        assert r.status == 200
        assert store.bindings[FOREIGN_SID] == ["kb-mine-1"]


async def test_get_drops_deleted_and_unreadable_bases(env):
    app, token, store = env
    # Binding rows survive base deletion/permission loss; GET must hide them.
    store.bindings[OWN_SID] = ["kb-mine-1", "kb-deleted", "kb-bob"]
    async with TestClient(TestServer(app)) as client:
        r = await client.get(_url(OWN_SID), headers=_hdr(token))
        assert r.status == 200
        data = await r.json()
        assert data["kb_ids"] == ["kb-mine-1"]

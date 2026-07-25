"""Integration tests for the knowledge-base API.

Exercises the full aiohttp route stack (auth gate + tenant scoping + multipart
upload + debug search) against an in-memory fake store, so no PostgreSQL or
embedding backend is required. Mirrors the TestServer/TestClient harness used
by test_expert_injection.py.
"""

from __future__ import annotations

import io

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

import xiaopaw.frontend.routes.knowledge as kb_routes
from xiaopaw.frontend.routes.knowledge import register_knowledge_routes


# ── in-memory fakes ───────────────────────────────────────────────────────────


class _FakeStore:
    """Minimal in-memory stand-in for KnowledgeStore (single shared instance)."""

    def __init__(self) -> None:
        self.bases: dict[str, dict] = {}
        self.documents: dict[str, dict] = {}
        self._seq = 0

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    # bases
    def create_base(self, *, name, scope, owner_key, org_id, description, created_by):
        kb_id = self._next("kb")
        self.bases[kb_id] = {
            "id": kb_id, "name": name, "scope": scope, "owner_key": owner_key,
            "org_id": org_id, "description": description, "created_by": created_by,
        }
        return {"id": kb_id, "name": name, "scope": scope}

    def list_bases(self, *, owner_key, org_id):
        out = []
        for b in self.bases.values():
            if b["scope"] == "personal" and b["owner_key"] == owner_key:
                out.append({**b, "document_count": 0})
            elif b["scope"] == "org" and org_id is not None and b["org_id"] == org_id:
                out.append({**b, "document_count": 0})
        return out

    def get_base(self, kb_id):
        return self.bases.get(kb_id)

    def delete_base(self, kb_id):
        self.bases.pop(kb_id, None)

    @staticmethod
    def can_access(base, *, owner_key, org_id):
        if base["scope"] == "personal":
            return base["owner_key"] == owner_key
        return org_id is not None and base["org_id"] == org_id

    # documents
    def create_document(self, *, kb_id, title, source_type, source_uri, mime, byte_size, created_by):
        doc_id = self._next("doc")
        self.documents[doc_id] = {
            "id": doc_id, "kb_id": kb_id, "title": title, "source_type": source_type,
            "source_uri": source_uri, "mime": mime, "byte_size": byte_size,
            "status": "pending", "error_msg": "", "chunk_count": 0, "created_by": created_by,
        }
        return doc_id

    def set_document_source_uri(self, doc_id, source_uri):
        self.documents[doc_id]["source_uri"] = source_uri

    def list_documents(self, kb_id):
        return [d for d in self.documents.values() if d["kb_id"] == kb_id]

    def get_document(self, doc_id):
        return self.documents.get(doc_id)

    def get_document_chunks(self, doc_id, *, limit=50, offset=0):
        return []

    def delete_document(self, doc_id):
        self.documents.pop(doc_id, None)


class _FakeUserAuth:
    """Maps bearer tokens to user dicts for check_auth + get_current_user."""

    def __init__(self, tokens: dict[str, dict]) -> None:
        self._tokens = tokens

    def validate_token(self, token):
        return self._tokens.get(token)

    def get_user_by_token(self, token):
        return self._tokens.get(token)


ALICE = {"id": 1, "username": "alice", "is_admin": False, "org_id": 5}
ADMIN = {"id": 2, "username": "admin", "is_admin": True, "org_id": 5}
BOB = {"id": 3, "username": "bob", "is_admin": False, "org_id": 9}


@pytest.fixture
def store():
    return _FakeStore()


@pytest.fixture
def app(store, monkeypatch, tmp_path):
    # Route the store accessor + async ingest to in-memory fakes. The real
    # KnowledgeStore class stays in place so KnowledgeStore.can_access (used by
    # the tenant permission checks) keeps working.
    monkeypatch.setattr(kb_routes, "_get_store", lambda request: store)
    scheduled: list[str] = []
    monkeypatch.setattr(kb_routes, "schedule_ingest", lambda s, doc_id: scheduled.append(doc_id))

    application = web.Application()
    application["scheduled"] = scheduled

    class _PgStore:
        _available = True
        _dsn = "postgresql://fake"

    application["pg_store"] = _PgStore()
    application["workspace_dir"] = str(tmp_path)
    application["user_auth"] = _FakeUserAuth({
        "tok-alice": ALICE,
        "tok-admin": ADMIN,
        "tok-bob": BOB,
    })
    register_knowledge_routes(application)
    return application


@pytest.fixture
async def client(app):
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _file_form(filename: str, content: bytes, content_type: str) -> FormData:
    """Build a real multipart/form-data body with a single file part."""
    form = FormData()
    form.add_field("file", io.BytesIO(content), filename=filename, content_type=content_type)
    return form


# ── auth gate ─────────────────────────────────────────────────────────────────


async def test_requires_auth(client):
    resp = await client.get("/api/frontend/knowledge/bases")
    assert resp.status == 401
    resp.close()


# ── personal base lifecycle + upload + search ─────────────────────────────────


async def test_full_personal_flow(client, monkeypatch):
    # create
    resp = await client.post(
        "/api/frontend/knowledge/bases",
        json={"name": "我的资料", "scope": "personal"},
        headers=_hdr("tok-alice"),
    )
    assert resp.status == 201
    kb_id = (await resp.json())["id"]
    resp.close()

    # list shows it
    resp = await client.get("/api/frontend/knowledge/bases", headers=_hdr("tok-alice"))
    bases = (await resp.json())["bases"]
    assert any(b["id"] == kb_id for b in bases)
    resp.close()

    # upload a document -> 202 + ingest scheduled
    resp = await client.post(
        f"/api/frontend/knowledge/bases/{kb_id}/documents",
        data=_file_form("note.txt", "知识内容".encode(), "text/plain"),
        headers=_hdr("tok-alice"),
    )
    assert resp.status == 202
    doc = await resp.json()
    assert doc["status"] == "pending"
    resp.close()
    assert client.app["scheduled"] == [doc["id"]]

    # document list reflects it
    resp = await client.get(
        f"/api/frontend/knowledge/bases/{kb_id}/documents", headers=_hdr("tok-alice")
    )
    docs = (await resp.json())["documents"]
    assert len(docs) == 1 and docs[0]["title"] == "note.txt"
    resp.close()

    # debug search returns citations (retrieve is stubbed)
    from xiaopaw.knowledge.retriever import RetrievedChunk

    def _fake_retrieve(store, *, query, owner_key, org_id, kb_id=None, top_k=6):
        assert owner_key == "p2p:web_alice"  # tenant derived from token, not body
        return [RetrievedChunk(
            n=1, chunk_id="c1", document_id="doc-1", kb_id="kb-1", chunk_index=0,
            document_title="note.txt", locator="", content="命中片段",
        )]

    monkeypatch.setattr(kb_routes, "retrieve", _fake_retrieve)
    resp = await client.post(
        "/api/frontend/knowledge/search",
        json={"query": "知识", "owner_key": "p2p:web_hacker"},
        headers=_hdr("tok-alice"),
    )
    assert resp.status == 200
    citations = (await resp.json())["citations"]
    assert citations[0]["snippet"] == "命中片段"
    resp.close()


async def test_upload_rejects_unsupported_type(client):
    resp = await client.post(
        "/api/frontend/knowledge/bases",
        json={"name": "库", "scope": "personal"}, headers=_hdr("tok-alice"),
    )
    kb_id = (await resp.json())["id"]
    resp.close()

    form = _file_form("evil.exe", b"MZ", "application/octet-stream")
    resp = await client.post(
        f"/api/frontend/knowledge/bases/{kb_id}/documents", data=form, headers=_hdr("tok-alice")
    )
    assert resp.status == 415
    resp.close()


# ── tenant isolation ──────────────────────────────────────────────────────────


async def test_cross_tenant_access_is_forbidden(client):
    # alice creates a personal base
    resp = await client.post(
        "/api/frontend/knowledge/bases",
        json={"name": "私密", "scope": "personal"}, headers=_hdr("tok-alice"),
    )
    kb_id = (await resp.json())["id"]
    resp.close()

    # bob (different tenant) cannot list documents or delete it
    resp = await client.get(
        f"/api/frontend/knowledge/bases/{kb_id}/documents", headers=_hdr("tok-bob")
    )
    assert resp.status == 403
    resp.close()

    resp = await client.delete(
        f"/api/frontend/knowledge/bases/{kb_id}", headers=_hdr("tok-bob")
    )
    assert resp.status == 403
    resp.close()

    # bob does not see alice's base in his list
    resp = await client.get("/api/frontend/knowledge/bases", headers=_hdr("tok-bob"))
    assert all(b["id"] != kb_id for b in (await resp.json())["bases"])
    resp.close()


# ── org base admin gating ─────────────────────────────────────────────────────


async def test_org_base_creation_requires_admin(client):
    # non-admin org member is refused
    resp = await client.post(
        "/api/frontend/knowledge/bases",
        json={"name": "团队库", "scope": "org"}, headers=_hdr("tok-alice"),
    )
    assert resp.status == 403
    resp.close()

    # admin succeeds
    resp = await client.post(
        "/api/frontend/knowledge/bases",
        json={"name": "团队库", "scope": "org"}, headers=_hdr("tok-admin"),
    )
    assert resp.status == 201
    kb_id = (await resp.json())["id"]
    resp.close()

    # same-org non-admin can read (list documents) but not delete
    resp = await client.get(
        f"/api/frontend/knowledge/bases/{kb_id}/documents", headers=_hdr("tok-alice")
    )
    assert resp.status == 200
    resp.close()

    resp = await client.delete(
        f"/api/frontend/knowledge/bases/{kb_id}", headers=_hdr("tok-alice")
    )
    assert resp.status == 403
    resp.close()

"""Unit tests for KnowledgeStore tenant scoping (can_access + search SQL)."""

from __future__ import annotations

from xiaopaw.knowledge.store import KnowledgeStore


# ── can_access: the read-permission matrix ────────────────────────────────────


def test_personal_base_only_visible_to_owner():
    base = {"scope": "personal", "owner_key": "p2p:web_alice", "org_id": None}
    assert KnowledgeStore.can_access(base, owner_key="p2p:web_alice", org_id=None)
    assert not KnowledgeStore.can_access(base, owner_key="p2p:web_bob", org_id=None)
    # org membership does not grant access to someone else's personal base
    assert not KnowledgeStore.can_access(base, owner_key="p2p:web_bob", org_id=1)


def test_org_base_visible_to_same_org_members():
    base = {"scope": "org", "owner_key": "p2p:web_admin", "org_id": 5}
    assert KnowledgeStore.can_access(base, owner_key="p2p:web_bob", org_id=5)
    assert not KnowledgeStore.can_access(base, owner_key="p2p:web_bob", org_id=6)
    # users with no org cannot see any org base
    assert not KnowledgeStore.can_access(base, owner_key="p2p:web_bob", org_id=None)


# ── search_candidates: tenant filter is always present in SQL ──────────────────


class _FakeCursor:
    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._sink.append((sql, params))

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self._sink)


def _store_with_capture(monkeypatch):
    store = KnowledgeStore("postgresql://ignored")
    sink: list = []
    monkeypatch.setattr(store, "_conn", lambda: _FakeConn(sink))
    return store, sink


def test_search_candidates_always_scopes_by_tenant(monkeypatch):
    store, sink = _store_with_capture(monkeypatch)
    store.search_candidates(
        query_vec=[0.1, 0.2],
        query_text="关键词",
        owner_key="p2p:web_alice",
        org_id=3,
        kb_id=None,
        limit=20,
    )

    assert len(sink) == 2  # one vector query, one full-text query
    for sql, params in sink:
        # Tenant predicates must appear in both branches.
        assert "kb.owner_key = %(owner_key)s" in sql
        assert "kb.org_id = %(org_id)s" in sql
        assert params["owner_key"] == "p2p:web_alice"
        assert params["org_id"] == 3
        # kb filter omitted when not scoped to specific bases
        assert "c.kb_id = ANY" not in sql


def test_search_candidates_adds_kb_filter_when_scoped(monkeypatch):
    store, sink = _store_with_capture(monkeypatch)
    store.search_candidates(
        query_vec=[0.1],
        query_text="q",
        owner_key="p2p:web_alice",
        org_id=None,
        kb_id="kb-123",
        limit=10,
    )
    for sql, params in sink:
        # Legacy single kb_id is normalized into the kb_ids list filter.
        assert "c.kb_id = ANY(%(kb_ids)s)" in sql
        assert params["kb_ids"] == ["kb-123"]


def test_search_candidates_kb_ids_multi_base_allowlist(monkeypatch):
    store, sink = _store_with_capture(monkeypatch)
    store.search_candidates(
        query_vec=[0.1],
        query_text="q",
        owner_key="p2p:web_alice",
        org_id=None,
        kb_ids=["kb-a", "kb-b"],
        limit=10,
    )
    for sql, params in sink:
        assert "c.kb_id = ANY(%(kb_ids)s)" in sql
        assert params["kb_ids"] == ["kb-a", "kb-b"]


def test_search_candidates_kb_ids_takes_priority_over_kb_id(monkeypatch):
    store, sink = _store_with_capture(monkeypatch)
    store.search_candidates(
        query_vec=[0.1],
        query_text="q",
        owner_key="p2p:web_alice",
        org_id=None,
        kb_id="kb-legacy",
        kb_ids=["kb-a", "kb-b"],
        limit=10,
    )
    for _sql, params in sink:
        assert params["kb_ids"] == ["kb-a", "kb-b"]


def test_search_candidates_empty_kb_ids_means_no_filter(monkeypatch):
    store, sink = _store_with_capture(monkeypatch)
    store.search_candidates(
        query_vec=[0.1],
        query_text="q",
        owner_key="p2p:web_alice",
        org_id=None,
        kb_ids=[],
        limit=10,
    )
    for sql, _params in sink:
        assert "c.kb_id = ANY" not in sql

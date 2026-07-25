"""Unit tests for hybrid retrieval: RRF fusion + tenant-scoped assembly."""

from __future__ import annotations

import sys
import types

from xiaopaw.knowledge import retriever
from xiaopaw.knowledge.retriever import (
    format_for_agent,
    rrf_fuse,
    to_citations,
)


# ── rrf_fuse (pure) ───────────────────────────────────────────────────────────


def test_rrf_prefers_ids_ranked_high_in_both_lists():
    vector = ["a", "b", "c"]
    text = ["b", "a", "d"]
    fused = rrf_fuse(vector, text, top_k=4)
    # "a" and "b" appear in both lists; both outrank single-list "c"/"d".
    assert set(fused[:2]) == {"a", "b"}
    assert fused[0] == "a"  # a is rank1+rank2 vs b rank2+rank1 -> tie, order breaks to a


def test_rrf_respects_top_k():
    fused = rrf_fuse(["a", "b", "c", "d"], ["e", "f"], top_k=3)
    assert len(fused) == 3


def test_rrf_deterministic_tie_break_by_first_appearance():
    # Disjoint lists, same rank -> order by vector-list-first appearance.
    fused = rrf_fuse(["x"], ["y"], top_k=2)
    assert fused == ["x", "y"]


def test_rrf_empty_inputs():
    assert rrf_fuse([], [], top_k=5) == []


# ── to_citations / format_for_agent ───────────────────────────────────────────


def _chunk(n, cid, doc_id="doc-1", idx=0, title="文档", locator="page=1", content="片段内容"):
    return retriever.RetrievedChunk(
        n=n,
        chunk_id=cid,
        document_id=doc_id,
        kb_id="kb-1",
        chunk_index=idx,
        document_title=title,
        locator=locator,
        content=content,
    )


def test_to_citations_shape():
    cits = to_citations([_chunk(1, "c1")])
    assert cits == [
        {
            "n": 1,
            "document_id": "doc-1",
            "chunk_index": 0,
            "title": "文档",
            "locator": "page=1",
            "snippet": "片段内容",
        }
    ]


def test_format_for_agent_numbers_and_lists_sources():
    out = format_for_agent([_chunk(1, "c1"), _chunk(2, "c2", title="第二篇")])
    assert "[1]" in out and "[2]" in out
    assert "来源列表" in out
    assert "第二篇" in out


def test_format_for_agent_empty():
    assert "未检索到" in format_for_agent([])


# ── retrieve() wiring: tenant params flow through, RRF drives order ────────────


class _FakeStore:
    """Captures the tenant params passed to search_candidates."""

    def __init__(self, vector_rows, text_rows):
        self._vector = vector_rows
        self._text = text_rows
        self.captured: dict = {}

    def search_candidates(self, **kwargs):
        self.captured = kwargs
        return self._vector, self._text


def _row(cid, doc_id, idx, content, title="标题", locator=""):
    return {
        "id": cid,
        "doc_id": doc_id,
        "kb_id": "kb-1",
        "chunk_index": idx,
        "content": content,
        "document_title": title,
        "locator": locator,
    }


def _stub_embedder(monkeypatch):
    """Install a fake xiaopaw.knowledge.embedder so no network/keys are needed."""
    fake = types.ModuleType("xiaopaw.knowledge.embedder")
    fake.embed_query = lambda text: [0.1, 0.2, 0.3]
    fake.embed_texts = lambda texts, **_: [[0.1, 0.2, 0.3] for _ in texts]
    monkeypatch.setitem(sys.modules, "xiaopaw.knowledge.embedder", fake)


def test_retrieve_blank_query_short_circuits(monkeypatch):
    store = _FakeStore([], [])
    assert retriever.retrieve(store, query="   ", owner_key="p2p:web_a", org_id=None) == []
    # Never touched the store.
    assert store.captured == {}


def test_retrieve_passes_tenant_scope_and_fuses(monkeypatch):
    _stub_embedder(monkeypatch)
    vector_rows = [_row("c1", "doc-1", 0, "向量命中一"), _row("c2", "doc-1", 1, "向量命中二")]
    text_rows = [_row("c2", "doc-1", 1, "向量命中二"), _row("c3", "doc-2", 0, "全文命中三")]
    store = _FakeStore(vector_rows, text_rows)

    results = retriever.retrieve(
        store,
        query="关键词",
        owner_key="p2p:web_alice",
        org_id=7,
        kb_id="kb-1",
        top_k=3,
    )

    # Tenant scope forwarded verbatim to the store (SQL enforces it).
    assert store.captured["owner_key"] == "p2p:web_alice"
    assert store.captured["org_id"] == 7
    assert store.captured["kb_id"] == "kb-1"

    # c2 ranks in both lists -> should lead; citation numbers are 1-based.
    assert results[0].chunk_id == "c2"
    assert [r.n for r in results] == list(range(1, len(results) + 1))
    ids = {r.chunk_id for r in results}
    assert ids == {"c1", "c2", "c3"}


def test_retrieve_forwards_kb_ids_allowlist(monkeypatch):
    _stub_embedder(monkeypatch)
    store = _FakeStore([], [])

    retriever.retrieve(
        store,
        query="关键词",
        owner_key="p2p:web_alice",
        org_id=None,
        kb_ids=["kb-a", "kb-b"],
    )

    # The session allowlist is passed through verbatim to the store.
    assert store.captured["kb_ids"] == ["kb-a", "kb-b"]
    assert store.captured["kb_id"] is None

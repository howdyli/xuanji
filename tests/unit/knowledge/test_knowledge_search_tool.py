"""Unit tests for KnowledgeSearchTool (agent-facing hybrid retrieval)."""

from __future__ import annotations

from xiaopaw.tools import KnowledgeSearchTool


def test_missing_dsn_returns_friendly_message():
    tool = KnowledgeSearchTool(routing_key="p2p:web_alice", db_dsn="")
    out = tool._run(query="任意问题")
    assert "未配置" in out


def test_blank_query_is_rejected():
    tool = KnowledgeSearchTool(routing_key="p2p:web_alice", db_dsn="postgresql://x")
    assert "不能为空" in tool._run(query="   ")


def test_run_injects_tenant_and_formats_results(monkeypatch):
    import xiaopaw.knowledge.retriever as retriever

    captured: dict = {}

    def _fake_retrieve(store, *, query, owner_key, org_id, kb_id=None, kb_ids=None, top_k=6):
        captured.update(
            query=query, owner_key=owner_key, org_id=org_id,
            kb_id=kb_id, kb_ids=kb_ids, top_k=top_k,
        )
        return [
            retriever.RetrievedChunk(
                n=1, chunk_id="c1", document_id="doc-1", kb_id="kb-1", chunk_index=0,
                document_title="产品手册", locator="page=2", content="关键结论内容",
            )
        ]

    monkeypatch.setattr(retriever, "retrieve", _fake_retrieve)

    tool = KnowledgeSearchTool(
        routing_key="p2p:web_alice", db_dsn="postgresql://x", org_id=5, default_top_k=6
    )
    out = tool._run(query="结论是什么", kb_id="kb-1", top_k=3)

    # Tenant context comes from the tool instance, never the LLM args.
    assert captured["owner_key"] == "p2p:web_alice"
    assert captured["org_id"] == 5
    assert captured["kb_id"] == "kb-1"
    assert captured["kb_ids"] is None  # no session allowlist -> unrestricted
    assert captured["top_k"] == 3
    # Numbered, citable output.
    assert "[1]" in out
    assert "产品手册" in out


def test_run_falls_back_to_default_top_k(monkeypatch):
    import xiaopaw.knowledge.retriever as retriever

    captured: dict = {}

    def _fake_retrieve(store, *, query, owner_key, org_id, kb_id=None, kb_ids=None, top_k=6):
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(retriever, "retrieve", _fake_retrieve)
    tool = KnowledgeSearchTool(routing_key="p2p:web_a", db_dsn="postgresql://x", default_top_k=9)
    tool._run(query="问题")
    assert captured["top_k"] == 9


# ── allowed_kb_ids: session-binding allowlist adjudication ──────────────────


def _capture_retrieve(monkeypatch):
    import xiaopaw.knowledge.retriever as retriever

    captured: dict = {}

    def _fake_retrieve(store, *, query, owner_key, org_id, kb_id=None, kb_ids=None, top_k=6):
        captured.update(kb_id=kb_id, kb_ids=kb_ids)
        return []

    monkeypatch.setattr(retriever, "retrieve", _fake_retrieve)
    return captured


def test_allowlist_restricts_when_llm_omits_kb_id(monkeypatch):
    captured = _capture_retrieve(monkeypatch)
    tool = KnowledgeSearchTool(
        routing_key="p2p:web_a", db_dsn="postgresql://x", allowed_kb_ids=["kb-1", "kb-2"]
    )
    out = tool._run(query="问题")
    assert captured["kb_ids"] == ["kb-1", "kb-2"]
    assert captured["kb_id"] is None
    assert "提示" not in out  # no notice when the LLM didn't pass kb_id


def test_allowlist_narrows_to_single_base_when_kb_id_in_list(monkeypatch):
    captured = _capture_retrieve(monkeypatch)
    tool = KnowledgeSearchTool(
        routing_key="p2p:web_a", db_dsn="postgresql://x", allowed_kb_ids=["kb-1", "kb-2"]
    )
    tool._run(query="问题", kb_id="kb-2")
    assert captured["kb_ids"] == ["kb-2"]
    assert captured["kb_id"] is None


def test_allowlist_ignores_out_of_list_kb_id_with_notice(monkeypatch):
    captured = _capture_retrieve(monkeypatch)
    tool = KnowledgeSearchTool(
        routing_key="p2p:web_a", db_dsn="postgresql://x", allowed_kb_ids=["kb-1"]
    )
    out = tool._run(query="问题", kb_id="kb-evil")
    # Falls back to the whole allowlist instead of failing the call.
    assert captured["kb_ids"] == ["kb-1"]
    assert captured["kb_id"] is None
    assert "不在当前会话绑定" in out


def test_empty_allowlist_behaves_as_unrestricted(monkeypatch):
    captured = _capture_retrieve(monkeypatch)
    tool = KnowledgeSearchTool(
        routing_key="p2p:web_a", db_dsn="postgresql://x", allowed_kb_ids=[]
    )
    tool._run(query="问题", kb_id="kb-9")
    assert captured["kb_ids"] is None
    assert captured["kb_id"] == "kb-9"

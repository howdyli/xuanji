"""Hybrid retrieval over knowledge_chunks: vector + full-text fused via RRF.

``rrf_fuse`` is a pure function (unit-testable without a database). ``retrieve``
wires query embedding + tenant-scoped candidate fetch + fusion and returns
citation-ready fragments.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_RRF_K = 60  # standard Reciprocal Rank Fusion constant


@dataclass(frozen=True)
class RetrievedChunk:
    n: int  # 1-based citation number
    chunk_id: str
    document_id: str
    kb_id: str
    chunk_index: int
    document_title: str
    locator: str
    content: str


def rrf_fuse(
    vector_ranked: list[str],
    text_ranked: list[str],
    *,
    top_k: int,
    k: int = _RRF_K,
) -> list[str]:
    """Reciprocal Rank Fusion over two ranked id lists.

    score(id) = sum(1 / (k + rank)) across lists it appears in (rank 1-based).
    Ties broken by first appearance in the vector list, then the text list, so
    ordering is deterministic.
    """
    scores: dict[str, float] = {}
    order: dict[str, int] = {}
    seq = 0
    for ranked in (vector_ranked, text_ranked):
        for rank, cid in enumerate(ranked, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            if cid not in order:
                order[cid] = seq
                seq += 1

    fused = sorted(scores.keys(), key=lambda cid: (-scores[cid], order[cid]))
    return fused[:top_k]


def retrieve(
    store,
    *,
    query: str,
    owner_key: str,
    org_id: int | None,
    kb_id: str | None = None,
    kb_ids: list[str] | None = None,
    top_k: int = 6,
    candidate_limit: int = 20,
    reranker=None,
) -> list[RetrievedChunk]:
    """Embed the query, fetch tenant-scoped candidates, and fuse them.

    ``kb_ids`` (multi-base allowlist, e.g. session bindings) takes priority
    over the legacy single ``kb_id``; both only narrow within the tenant's
    visible set.
    """
    from xiaopaw.knowledge.embedder import embed_query

    if not query or not query.strip():
        return []

    query_vec = embed_query(query)
    vector_rows, text_rows = store.search_candidates(
        query_vec=query_vec,
        query_text=query,
        owner_key=owner_key,
        org_id=org_id,
        kb_id=kb_id,
        kb_ids=kb_ids,
        limit=candidate_limit,
    )

    by_id: dict[str, dict] = {}
    for row in (*vector_rows, *text_rows):
        by_id.setdefault(row["id"], row)

    fused_ids = rrf_fuse(
        [r["id"] for r in vector_rows],
        [r["id"] for r in text_rows],
        top_k=candidate_limit,
    )

    # Optional reranking
    if reranker is not None and fused_ids:
        import time as _time
        _rerank_start = _time.monotonic()
        contents = [by_id[cid]["content"] for cid in fused_ids]
        rerank_results = reranker.rerank(query, contents, top_n=top_k)
        fused_ids = [fused_ids[r["index"]] for r in rerank_results if r["index"] < len(fused_ids)]
        logger.info("rerank took %.3fs", _time.monotonic() - _rerank_start)
    else:
        fused_ids = fused_ids[:top_k]

    results: list[RetrievedChunk] = []
    for n, cid in enumerate(fused_ids, start=1):
        row = by_id[cid]
        results.append(
            RetrievedChunk(
                n=n,
                chunk_id=cid,
                document_id=row["doc_id"],
                kb_id=row["kb_id"],
                chunk_index=row["chunk_index"],
                document_title=row.get("document_title", ""),
                locator=row.get("locator", ""),
                content=row["content"],
            )
        )
    return results


def format_for_agent(chunks: list[RetrievedChunk], *, snippet_chars: int = 500) -> str:
    """Render fused chunks as a numbered block for the LLM to cite as ``[n]``."""
    if not chunks:
        return "（知识库中未检索到相关内容）"

    lines: list[str] = ["检索到的知识库片段（引用事实时请标注对应编号，如 [1]）：", ""]
    for c in chunks:
        loc = f" · {c.locator}" if c.locator else ""
        body = c.content.strip().replace("\n", " ")[:snippet_chars]
        lines.append(f"[{c.n}] 《{c.document_title}》{loc}\n{body}")
        lines.append("")
    lines.append("来源列表：")
    for c in chunks:
        loc = f" · {c.locator}" if c.locator else ""
        lines.append(f"[{c.n}] {c.document_title}{loc}")
    return "\n".join(lines).strip()


def to_citations(chunks: list[RetrievedChunk], *, snippet_chars: int = 200) -> list[dict]:
    """Structured citation payload for the frontend."""
    return [
        {
            "n": c.n,
            "document_id": c.document_id,
            "chunk_index": c.chunk_index,
            "title": c.document_title,
            "locator": c.locator,
            "snippet": c.content.strip().replace("\n", " ")[:snippet_chars],
        }
        for c in chunks
    ]

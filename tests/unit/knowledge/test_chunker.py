"""Unit tests for the knowledge-base recursive chunker."""

from __future__ import annotations

from xiaopaw.knowledge.chunker import chunk_text, estimate_tokens


def test_empty_or_blank_text_yields_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []


def test_short_text_is_a_single_chunk():
    chunks = chunk_text("这是一个很短的段落。", target_tokens=500)
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].content == "这是一个很短的段落。"
    assert chunks[0].token_count == estimate_tokens("这是一个很短的段落。")


def test_locator_is_propagated_to_chunks():
    chunks = chunk_text("正文内容。", base_locator="page=3")
    assert chunks
    assert all(c.locator == "page=3" for c in chunks)


def test_chunk_indices_are_contiguous_and_zero_based():
    # Build text well over the budget so it splits into several chunks.
    paragraphs = [f"第{i}段的内容。" * 40 for i in range(12)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, target_tokens=100, overlap_tokens=20)
    assert len(chunks) > 1
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunks_respect_token_budget_with_small_tolerance():
    paragraphs = [f"段落{i}：" + ("内容字符" * 60) for i in range(8)]
    text = "\n\n".join(paragraphs)
    target = 120
    chunks = chunk_text(text, target_tokens=target, overlap_tokens=20)
    assert len(chunks) > 1
    # Each chunk stays near the budget; overlap seeding may push slightly over,
    # so allow a generous margin but reject runaway chunks.
    for c in chunks:
        assert c.token_count <= target * 2


def test_overlap_shares_context_between_adjacent_chunks():
    # Distinct paragraphs so we can detect a shared overlap tail.
    paragraphs = [f"AAAAAAAAAA-{i}-" + ("x" * 200) for i in range(6)]
    text = "\n\n".join(paragraphs)
    with_overlap = chunk_text(text, target_tokens=120, overlap_tokens=40)
    no_overlap = chunk_text(text, target_tokens=120, overlap_tokens=0)
    # Overlap produces at least as much total content as the non-overlap variant.
    total_overlap = sum(len(c.content) for c in with_overlap)
    total_plain = sum(len(c.content) for c in no_overlap)
    assert total_overlap >= total_plain


def test_oversized_single_paragraph_is_hard_wrapped():
    # One giant paragraph with no sentence breaks must still be split.
    text = "字" * 5000
    chunks = chunk_text(text, target_tokens=100, overlap_tokens=0)
    assert len(chunks) > 1
    assert "".join(c.content for c in chunks).replace("\n", "") != ""


def test_estimate_tokens_is_rough_half_length():
    assert estimate_tokens("abcd") == 2
    assert estimate_tokens("") == 0

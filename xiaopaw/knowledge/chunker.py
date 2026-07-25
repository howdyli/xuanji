"""Recursive text chunker for knowledge-base ingestion.

Splits extracted document text into overlapping chunks bounded by a token
budget, preferring natural boundaries (headings -> paragraphs -> lines ->
sentences). Token counting reuses the repo's rough heuristic (``len // 2``)
so behaviour is deterministic and dependency-free in tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Rough token heuristic consistent with xiaopaw.memory.token_counter's
# "rough" mode (len(text) // 2). Kept local so chunking never depends on an
# optional tokenizer being installed.
_CHARS_PER_TOKEN = 2


def estimate_tokens(text: str) -> int:
    """Estimate token count for a text fragment (rough, deterministic)."""
    return max(0, len(text) // _CHARS_PER_TOKEN)


@dataclass(frozen=True)
class Chunk:
    """A single retrievable unit produced by the chunker."""

    index: int
    content: str
    token_count: int
    locator: str  # e.g. "page=3" / "heading=Introduction" / ""


# Split priority: markdown/section headings first, then blank-line paragraphs.
_HEADING_RE = re.compile(r"^(#{1,6})\s+.*$", re.MULTILINE)
_SENTENCE_RE = re.compile(r"(?<=[。！？.!?])\s+|\n{2,}")


def _split_paragraphs(text: str) -> list[str]:
    """Split into paragraph-ish blocks on blank lines, keeping non-empty parts."""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _split_sentences(text: str) -> list[str]:
    """Split an over-long paragraph into sentence-ish spans (CJK + latin)."""
    parts = _SENTENCE_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def chunk_text(
    text: str,
    *,
    target_tokens: int = 500,
    overlap_tokens: int = 80,
    base_locator: str = "",
) -> list[Chunk]:
    """Chunk ``text`` into ~``target_tokens`` pieces with ``overlap_tokens`` overlap.

    Paragraphs are packed greedily up to the token budget. A paragraph larger
    than the budget is further split into sentences. Consecutive chunks share a
    trailing/leading overlap window to preserve cross-boundary context.
    """
    if not text or not text.strip():
        return []

    target_chars = max(1, target_tokens * _CHARS_PER_TOKEN)
    overlap_chars = max(0, min(overlap_tokens, target_tokens) * _CHARS_PER_TOKEN)

    # Break paragraphs; explode any paragraph exceeding the budget into sentences.
    units: list[str] = []
    for para in _split_paragraphs(text):
        if len(para) <= target_chars:
            units.append(para)
            continue
        buf = ""
        for sent in _split_sentences(para):
            if buf and len(buf) + len(sent) + 1 > target_chars:
                units.append(buf)
                buf = sent
            else:
                buf = f"{buf} {sent}".strip() if buf else sent
            # A single sentence longer than the budget: hard-wrap.
            while len(buf) > target_chars:
                units.append(buf[:target_chars])
                buf = buf[target_chars:]
        if buf:
            units.append(buf)

    # Greedily pack units into chunks under the char budget.
    raw_chunks: list[str] = []
    buf = ""
    for unit in units:
        if buf and len(buf) + len(unit) + 2 > target_chars:
            raw_chunks.append(buf)
            # Seed the next buffer with an overlap tail of the previous chunk.
            buf = (buf[-overlap_chars:] + "\n\n" + unit) if overlap_chars else unit
        else:
            buf = f"{buf}\n\n{unit}" if buf else unit
    if buf.strip():
        raw_chunks.append(buf)

    return [
        Chunk(
            index=i,
            content=c.strip(),
            token_count=estimate_tokens(c),
            locator=base_locator,
        )
        for i, c in enumerate(raw_chunks)
        if c.strip()
    ]

"""Recursive text chunker for knowledge-base ingestion.

Splits extracted document text into overlapping chunks bounded by a token
budget, preferring natural boundaries (headings -> paragraphs -> lines ->
sentences). Token counting reuses the repo's rough heuristic (``len // 2``)
so behaviour is deterministic and dependency-free in tests.

Also provides a structure-aware chunking strategy that respects heading
boundaries, keeps markdown tables indivisible, and uses lightweight TF-IDF
cosine similarity to detect topic shifts.
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

# Structure-Aware chunking patterns
_TABLE_ROW_RE = re.compile(r"^\|.*\|$")  # Markdown table row
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|$")  # Markdown table separator
_HEADING_RE_SA = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def _split_paragraphs(text: str) -> list[str]:
    """Split into paragraph-ish blocks on blank lines, keeping non-empty parts."""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _split_sentences(text: str) -> list[str]:
    """Split an over-long paragraph into sentence-ish spans (CJK + latin)."""
    parts = _SENTENCE_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    *,
    strategy: str = "recursive",
    target_tokens: int = 500,
    overlap_tokens: int = 80,
    base_locator: str = "",
    **kwargs,
) -> list[Chunk]:
    """Chunk text using the specified strategy."""
    if strategy == "structure_aware":
        return _structure_aware_chunk(text, base_locator=base_locator, **kwargs)
    # Default: recursive (existing logic)
    return _recursive_chunk(
        text,
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
        base_locator=base_locator,
    )


# ---------------------------------------------------------------------------
# Strategy 1: Recursive (original) chunking
# ---------------------------------------------------------------------------

def _recursive_chunk(
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


# ---------------------------------------------------------------------------
# Strategy 2: Structure-Aware chunking
# ---------------------------------------------------------------------------

def _structure_aware_chunk(
    text: str,
    base_locator: str = "",
    topic_similarity_threshold: float = 0.2,
    max_chunk_tokens: int = 800,
    min_chunk_tokens: int = 100,
) -> list[Chunk]:
    """Structure-aware chunking with heading boundaries, table preservation, and topic detection."""

    # Step 1: Split into structural units (headings, paragraphs, tables)
    units = _split_structural(text)

    # Step 2: Group units into chunks respecting boundaries
    chunks = _group_into_chunks(
        units,
        max_tokens=max_chunk_tokens,
        min_tokens=min_chunk_tokens,
        topic_threshold=topic_similarity_threshold,
    )

    return [
        Chunk(
            index=i,
            content=c["content"].strip(),
            token_count=estimate_tokens(c["content"]),
            locator=c.get("locator", base_locator),
        )
        for i, c in enumerate(chunks)
        if c["content"].strip()
    ]


def _split_structural(text: str) -> list[dict]:
    """Split text into structural units: headings, paragraphs, tables.

    Returns list of {type: "heading"|"paragraph"|"table", content: str, locator: str}
    """
    units: list[dict] = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Heading detection → hard boundary
        heading_match = _HEADING_RE_SA.match(line)
        if heading_match:
            units.append({
                "type": "heading",
                "content": line,
                "locator": f"heading={heading_match.group(2).strip()}",
            })
            i += 1
            continue

        # Table detection → collect all consecutive table rows
        if _TABLE_ROW_RE.match(line.strip()):
            table_lines = [line]
            i += 1
            while i < len(lines) and (
                _TABLE_ROW_RE.match(lines[i].strip())
                or _TABLE_SEP_RE.match(lines[i].strip())
            ):
                table_lines.append(lines[i])
                i += 1
            units.append({
                "type": "table",
                "content": "\n".join(table_lines),
                "locator": "",
            })
            continue

        # Empty line → skip (paragraph separator)
        if not line.strip():
            i += 1
            continue

        # Regular paragraph text → collect until empty line or structural element
        para_lines = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i]
            if not next_line.strip():
                break
            if _HEADING_RE_SA.match(next_line):
                break
            if _TABLE_ROW_RE.match(next_line.strip()):
                break
            para_lines.append(next_line)
            i += 1

        units.append({
            "type": "paragraph",
            "content": "\n".join(para_lines),
            "locator": "",
        })

    return units


def _group_into_chunks(
    units: list[dict],
    *,
    max_tokens: int = 800,
    min_tokens: int = 100,
    topic_threshold: float = 0.2,
) -> list[dict]:
    """Group structural units into chunks, respecting boundaries."""
    if not units:
        return []

    chunks: list[dict] = []
    current_parts: list[str] = []
    current_tokens = 0
    current_locator = ""

    for unit in units:
        unit_text = unit["content"]
        unit_tokens = estimate_tokens(unit_text)

        # Heading = hard boundary: flush current chunk first
        if unit["type"] == "heading":
            if current_parts:
                chunks.append({
                    "content": "\n\n".join(current_parts),
                    "locator": current_locator,
                })
                current_parts = []
                current_tokens = 0
            current_locator = unit.get("locator", "")
            current_parts.append(unit_text)
            current_tokens += unit_tokens
            continue

        # Table = indivisible: if adding it exceeds max, flush first
        if unit["type"] == "table":
            if current_tokens + unit_tokens > max_tokens and current_parts:
                chunks.append({
                    "content": "\n\n".join(current_parts),
                    "locator": current_locator,
                })
                current_parts = []
                current_tokens = 0
            # If table alone exceeds max, truncate with header
            if unit_tokens > max_tokens:
                truncated = _truncate_table(unit_text, max_tokens)
                chunks.append({"content": truncated, "locator": "table=truncated"})
            else:
                current_parts.append(unit_text)
                current_tokens += unit_tokens
            continue

        # Paragraph: check topic similarity with previous paragraph
        if current_parts and current_tokens >= min_tokens:
            prev_text = current_parts[-1] if current_parts else ""
            if _topic_dissimilar(prev_text, unit_text, threshold=topic_threshold):
                chunks.append({
                    "content": "\n\n".join(current_parts),
                    "locator": current_locator,
                })
                current_parts = []
                current_tokens = 0

        # Check if adding this paragraph exceeds max
        if current_tokens + unit_tokens > max_tokens and current_parts:
            chunks.append({
                "content": "\n\n".join(current_parts),
                "locator": current_locator,
            })
            current_parts = []
            current_tokens = 0

        current_parts.append(unit_text)
        current_tokens += unit_tokens

    # Flush remaining
    if current_parts:
        chunks.append({
            "content": "\n\n".join(current_parts),
            "locator": current_locator,
        })

    return chunks


def _topic_dissimilar(text_a: str, text_b: str, *, threshold: float = 0.2) -> bool:
    """Check if two texts are topically dissimilar using lightweight TF-IDF cosine.

    Pure local implementation using term frequency vectors — no external dependencies.
    Returns True if cosine similarity < threshold (topic break detected).
    """
    if not text_a or not text_b:
        return False

    # Simple word frequency vectors (CJK character bigrams + latin words)
    def _term_freq(text: str) -> dict[str, int]:
        freq: dict[str, int] = {}
        # Latin words
        for word in re.findall(r"[a-zA-Z]{2,}", text.lower()):
            freq[word] = freq.get(word, 0) + 1
        # CJK character bigrams
        cjk_chars = re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]", text)
        for i in range(len(cjk_chars) - 1):
            bigram = cjk_chars[i] + cjk_chars[i + 1]
            freq[bigram] = freq.get(bigram, 0) + 1
        return freq

    freq_a = _term_freq(text_a)
    freq_b = _term_freq(text_b)

    if not freq_a or not freq_b:
        return False

    # Cosine similarity
    common_keys = set(freq_a) & set(freq_b)
    if not common_keys:
        return True  # No common terms → completely dissimilar

    dot_product = sum(freq_a[k] * freq_b[k] for k in common_keys)
    norm_a = sum(v * v for v in freq_a.values()) ** 0.5
    norm_b = sum(v * v for v in freq_b.values()) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return True

    cosine = dot_product / (norm_a * norm_b)
    return cosine < threshold


def _truncate_table(table_text: str, max_tokens: int) -> str:
    """Truncate a markdown table to fit within token budget, keeping header."""
    lines = table_text.split("\n")
    if len(lines) < 3:
        return table_text[: max_tokens * 2]

    header = lines[0]
    separator = lines[1]
    body_lines = lines[2:]

    result = [header, separator]
    current_tokens = estimate_tokens(header + separator)

    for line in body_lines:
        line_tokens = estimate_tokens(line)
        if current_tokens + line_tokens > max_tokens:
            break
        result.append(line)
        current_tokens += line_tokens

    return "\n".join(result)

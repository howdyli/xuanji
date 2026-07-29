"""Tests for knowledge chunker: recursive + structure-aware strategies."""

from __future__ import annotations

import pytest

from xiaopaw.knowledge.chunker import (
    Chunk,
    _group_into_chunks,
    _split_structural,
    _topic_dissimilar,
    _truncate_table,
    chunk_text,
)


# ---------------------------------------------------------------------------
# Recursive chunking (default strategy)
# ---------------------------------------------------------------------------

def test_recursive_chunk_basic():
    """Default recursive chunking still works after refactor."""
    text = "Hello world.\n\nThis is a test paragraph with some content."
    chunks = chunk_text(text)
    assert isinstance(chunks, list)
    assert all(isinstance(c, Chunk) for c in chunks)
    assert len(chunks) >= 1
    # Content should be preserved
    combined = " ".join(c.content for c in chunks)
    assert "Hello world" in combined
    assert "test paragraph" in combined


def test_recursive_chunk_empty():
    """Empty text returns empty list."""
    assert chunk_text("") == []
    assert chunk_text("   ") == []


# ---------------------------------------------------------------------------
# Structure-Aware: heading boundary
# ---------------------------------------------------------------------------

def test_structure_aware_heading_boundary():
    """Headings force a hard chunk boundary."""
    text = (
        "# Introduction\n\n"
        "This is the intro paragraph.\n\n"
        "# Methods\n\n"
        "This is the methods section."
    )
    chunks = chunk_text(text, strategy="structure_aware")
    assert len(chunks) >= 2
    # First chunk should contain intro, second should contain methods
    contents = [c.content for c in chunks]
    assert any("Introduction" in c for c in contents)
    assert any("Methods" in c for c in contents)
    # Locator should reflect heading
    locators = [c.locator for c in chunks]
    assert any("heading=Introduction" in loc for loc in locators)


# ---------------------------------------------------------------------------
# Structure-Aware: table indivisible
# ---------------------------------------------------------------------------

def test_structure_aware_table_indivisible():
    """Tables are kept together and not split across chunks."""
    text = (
        "# Data\n\n"
        "Here is a table:\n\n"
        "| Name | Age |\n"
        "|------|-----|\n"
        "| Alice | 30 |\n"
        "| Bob   | 25 |\n"
        "\n"
        "Some concluding text."
    )
    chunks = chunk_text(text, strategy="structure_aware")
    # Find the chunk containing the table
    table_chunks = [c for c in chunks if "| Alice |" in c.content]
    assert len(table_chunks) == 1
    # Table header and body should be in the same chunk
    assert "| Name | Age |" in table_chunks[0].content
    assert "| Bob   | 25 |" in table_chunks[0].content


# ---------------------------------------------------------------------------
# Structure-Aware: table truncation
# ---------------------------------------------------------------------------

def test_structure_aware_table_truncation():
    """Oversized tables are truncated but header is preserved."""
    # Build a large table
    header = "| Col1 | Col2 |"
    sep = "|------|------|"
    rows = [f"| value{i} | data{i} |" for i in range(200)]
    text = header + "\n" + sep + "\n" + "\n".join(rows)

    # Use very small max_chunk_tokens to force truncation
    chunks = chunk_text(
        text,
        strategy="structure_aware",
        max_chunk_tokens=50,
        min_chunk_tokens=10,
    )
    # At least one chunk should be produced
    assert len(chunks) >= 1
    # The truncated table should contain the header
    first_chunk = chunks[0]
    assert "| Col1 | Col2 |" in first_chunk.content


# ---------------------------------------------------------------------------
# Topic detection (TF-IDF cosine)
# ---------------------------------------------------------------------------

def test_topic_dissimilar():
    """Completely different topics are detected as dissimilar."""
    text_a = "Python programming language features and syntax"
    text_b = "Japanese cooking recipes for sushi and ramen"
    assert _topic_dissimilar(text_a, text_b, threshold=0.2) is True


def test_topic_similar():
    """Similar texts are NOT flagged as dissimilar."""
    text_a = "Python programming language features and syntax"
    text_b = "Python programming language performance and optimization"
    assert _topic_dissimilar(text_a, text_b, threshold=0.2) is False


# ---------------------------------------------------------------------------
# Strategy parameter dispatch
# ---------------------------------------------------------------------------

def test_chunk_text_strategy_param():
    """chunk_text dispatches to the correct strategy based on the param."""
    text = "# Title\n\nParagraph one.\n\n# Section\n\nParagraph two."

    recursive_chunks = chunk_text(text, strategy="recursive")
    sa_chunks = chunk_text(text, strategy="structure_aware")

    # Both should produce chunks
    assert len(recursive_chunks) >= 1
    assert len(sa_chunks) >= 1

    # Structure-aware should produce at least as many chunks due to heading boundaries
    assert len(sa_chunks) >= len(recursive_chunks)


# ---------------------------------------------------------------------------
# Empty text
# ---------------------------------------------------------------------------

def test_empty_text():
    """Empty text returns empty list for both strategies."""
    assert chunk_text("", strategy="recursive") == []
    assert chunk_text("", strategy="structure_aware") == []
    assert chunk_text("   ", strategy="structure_aware") == []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def test_split_structural_types():
    """_split_structural correctly identifies headings, paragraphs, tables."""
    text = (
        "# Heading\n\n"
        "A paragraph.\n\n"
        "| A | B |\n"
        "|---|---|\n"
        "| 1 | 2 |"
    )
    units = _split_structural(text)
    types = [u["type"] for u in units]
    assert "heading" in types
    assert "paragraph" in types
    assert "table" in types


def test_truncate_table_preserves_header():
    """_truncate_table keeps header + separator even when truncating."""
    lines = ["| H1 | H2 |", "|---|---|"] + [f"| a{i} | b{i} |" for i in range(100)]
    table_text = "\n".join(lines)
    result = _truncate_table(table_text, max_tokens=20)
    result_lines = result.split("\n")
    assert result_lines[0] == "| H1 | H2 |"
    assert result_lines[1] == "|---|---|"
    # Should have fewer lines than original
    assert len(result_lines) < len(lines)

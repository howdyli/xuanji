"""Unit tests for FileAdapter text extraction (md/txt, docx, pdf)."""

from __future__ import annotations

import pytest

from xiaopaw.knowledge.adapters import (
    AdapterError,
    DocumentSource,
    FileAdapter,
    get_adapter,
)


def _src(path) -> DocumentSource:
    return DocumentSource(source_type="file", uri=str(path))


# ── plain text / markdown ─────────────────────────────────────────────────────


def test_extract_txt(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("第一行内容\n第二行内容\n", encoding="utf-8")
    result = FileAdapter().extract(_src(p))
    assert result.title == "note.txt"
    assert len(result.sections) == 1
    assert "第一行内容" in result.sections[0].text
    assert result.sections[0].locator == ""


def test_extract_markdown(tmp_path):
    p = tmp_path / "readme.md"
    p.write_text("# 标题\n\n正文段落。", encoding="utf-8")
    result = FileAdapter().extract(_src(p))
    assert "# 标题" in result.sections[0].text


def test_empty_text_file_raises(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("   \n  ", encoding="utf-8")
    with pytest.raises(AdapterError):
        FileAdapter().extract(_src(p))


# ── docx ──────────────────────────────────────────────────────────────────────


def test_extract_docx(tmp_path):
    docx = pytest.importorskip("docx")
    p = tmp_path / "spec.docx"
    document = docx.Document()
    document.add_paragraph("知识库设计文档")
    document.add_paragraph("这是第二段。")
    document.save(str(p))

    result = FileAdapter().extract(_src(p))
    assert result.title == "spec.docx"
    assert "知识库设计文档" in result.sections[0].text
    assert "第二段" in result.sections[0].text


# ── pdf ─────────────────────────────────────────────────────────────────────—


def _make_simple_pdf(text: str) -> bytes:
    """Assemble a minimal single-page PDF with an extractable text object."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = b"BT /F1 24 Tf 72 720 Td (" + text.encode("latin-1") + b") Tj ET"
    objects.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref_pos = len(pdf)
    size = len(objects) + 1
    pdf += b"xref\n0 " + str(size).encode() + b"\n"
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += ("%010d 00000 n \n" % off).encode()
    pdf += b"trailer\n<< /Size " + str(size).encode() + b" /Root 1 0 R >>\n"
    pdf += b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    return bytes(pdf)


def test_extract_pdf(tmp_path):
    pytest.importorskip("pypdf")
    p = tmp_path / "doc.pdf"
    p.write_bytes(_make_simple_pdf("HelloKnowledge"))

    result = FileAdapter().extract(_src(p))
    assert result.title == "doc.pdf"
    assert result.sections, "expected at least one page section"
    # First page locator is page-anchored for citations.
    assert result.sections[0].locator == "page=1"
    assert "Hello" in result.sections[0].text


# ── dispatch / error paths ────────────────────────────────────────────────────


def test_unsupported_extension_raises(tmp_path):
    p = tmp_path / "image.png"
    p.write_bytes(b"\x89PNG\r\n")
    with pytest.raises(AdapterError):
        FileAdapter().extract(_src(p))


def test_missing_file_raises(tmp_path):
    with pytest.raises(AdapterError):
        FileAdapter().extract(_src(tmp_path / "nope.txt"))


def test_get_adapter_rejects_non_file_source():
    with pytest.raises(AdapterError):
        get_adapter(DocumentSource(source_type="url", uri="https://example.com"))


def test_file_adapter_supports_only_file():
    adapter = FileAdapter()
    assert adapter.supports(DocumentSource(source_type="file", uri="x.txt"))
    assert not adapter.supports(DocumentSource(source_type="url", uri="x"))

"""Source adapters: turn an uploaded/imported source into extractable text.

Each adapter implements ``extract(source) -> ExtractResult`` returning a title
plus a list of ``Section`` (text + locator). Splitting the raw document into
sections (e.g. per PDF page) lets the chunker preserve citation anchors.

P0 ships ``FileAdapter`` (pdf/docx/md/txt). ``UrlAdapter`` (P1) and
``FeishuAdapter`` (P2) plug into the same protocol without touching the
ingestion pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Section:
    """A contiguous span of source text with a citation locator."""

    text: str
    locator: str = ""  # "page=3" / "heading=..." / ""


@dataclass(frozen=True)
class ExtractResult:
    title: str
    sections: list[Section] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentSource:
    """Where a document comes from (P0 uses ``file``)."""

    source_type: str  # 'file' | 'url' | 'feishu'
    uri: str          # local file path / URL / feishu token
    title: str = ""
    mime: str = ""


class AdapterError(RuntimeError):
    """Raised when a source cannot be parsed into text."""


class SourceAdapter(Protocol):
    def supports(self, source: DocumentSource) -> bool: ...
    def extract(self, source: DocumentSource) -> ExtractResult: ...


# ── File adapter (P0) ────────────────────────────────────────────────────────

_TEXT_EXTS = {".md", ".markdown", ".txt", ".text", ""}


class FileAdapter:
    """Extract text from local files: pdf, docx, md, txt."""

    def supports(self, source: DocumentSource) -> bool:
        return source.source_type == "file"

    def extract(self, source: DocumentSource) -> ExtractResult:
        path = Path(source.uri)
        if not path.is_file():
            raise AdapterError(f"file not found: {source.uri}")

        ext = path.suffix.lower()
        title = source.title or path.name

        if ext == ".pdf":
            return ExtractResult(title=title, sections=self._extract_pdf(path))
        if ext in (".docx",):
            return ExtractResult(title=title, sections=self._extract_docx(path))
        if ext in _TEXT_EXTS:
            return ExtractResult(title=title, sections=self._extract_text(path))
        raise AdapterError(f"unsupported file type: {ext or '(none)'}")

    @staticmethod
    def _extract_text(path: Path) -> list[Section]:
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = path.read_text(encoding="utf-8", errors="replace")
        if not raw.strip():
            raise AdapterError("empty text file")
        return [Section(text=raw, locator="")]

    @staticmethod
    def _extract_pdf(path: Path) -> list[Section]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - env guard
            raise AdapterError("pypdf not installed; cannot parse PDF") from exc

        reader = PdfReader(str(path))
        sections: list[Section] = []
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                sections.append(Section(text=text, locator=f"page={i}"))
        if not sections:
            raise AdapterError("no extractable text in PDF (scanned image?)")
        return sections

    @staticmethod
    def _extract_docx(path: Path) -> list[Section]:
        try:
            import docx  # python-docx
        except ImportError as exc:  # pragma: no cover - env guard
            raise AdapterError("python-docx not installed; cannot parse DOCX") from exc

        document = docx.Document(str(path))
        paras = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        if not paras:
            raise AdapterError("no text in DOCX")
        return [Section(text="\n\n".join(paras), locator="")]


def get_adapter(source: DocumentSource) -> SourceAdapter:
    """Return the adapter that supports ``source`` (P0: file only)."""
    adapter = FileAdapter()
    if adapter.supports(source):
        return adapter
    raise AdapterError(f"no adapter for source_type={source.source_type!r}")

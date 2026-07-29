"""Source adapters: turn an uploaded/imported source into extractable text.

Each adapter implements ``extract(source) -> ExtractResult`` returning a title
plus a list of ``Section`` (text + locator). Splitting the raw document into
sections (e.g. per PDF page) lets the chunker preserve citation anchors.

P0 ships ``FileAdapter`` (pdf/docx/md/txt). ``UrlAdapter`` (P1) and
``FeishuAdapter`` (P2) plug into the same protocol without touching the
ingestion pipeline.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


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
        """Extract text from PDF.

        Three-level cascade:
        Level 1: pypdf pure text extraction
        Level 2: pdfplumber text + tables (when XIAOPAW_DEEP_PDF_PARSE enabled)
        Level 3: Vision-model OCR fallback (when XIAOPAW_OCR_ENABLED enabled)
        """
        # ── Level 2: deep PDF parse (pdfplumber) ────────────────────────
        enable_deep = os.environ.get("XIAOPAW_DEEP_PDF_PARSE", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if enable_deep:
            try:
                from xiaopaw.knowledge.pdf_parser import DeepPdfParser

                parser = DeepPdfParser()
                sections = parser.parse(path)
                if sections:
                    return sections
                logger.warning(
                    "deep PDF parse returned no sections, falling back to pypdf"
                )
            except ImportError:
                logger.warning("pdfplumber not installed, falling back to pypdf")
            except Exception as exc:
                logger.warning(
                    "deep PDF parse failed: %s, falling back to pypdf", exc
                )

        # ── Level 1: pypdf pure text extraction ─────────────────────────
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise AdapterError("pypdf not installed; cannot parse PDF") from exc

        reader = PdfReader(str(path))
        sections: list[Section] = []
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                sections.append(Section(text=text, locator=f"page={i}"))
        if sections:
            return sections

        # ── Level 3: Vision-model OCR fallback ──────────────────────────
        enable_ocr = os.environ.get("XIAOPAW_OCR_ENABLED", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if enable_ocr:
            ocr_sections = FileAdapter._ocr_fallback(path)
            if ocr_sections:
                logger.info("OCR fallback produced %d sections for %s", len(ocr_sections), path.name)
                return ocr_sections

        raise AdapterError("no extractable text in PDF (scanned image?)")

    @staticmethod
    def _ocr_fallback(path: Path) -> list[Section]:
        """Attempt OCR on a scanned PDF using pdf2image + vision model.

        Returns an empty list when any dependency is missing or OCR fails,
        so the caller can decide whether to raise.
        """
        try:
            from pdf2image import convert_from_path
        except ImportError:
            logger.warning("OCR fallback: pdf2image not installed")
            return []

        try:
            from xiaopaw.knowledge.vision_ocr import VisionOCR
        except ImportError:
            logger.warning("OCR fallback: vision_ocr module unavailable")
            return []

        page_limit = int(os.environ.get("XIAOPAW_OCR_PAGE_LIMIT", "50"))
        timeout = int(os.environ.get("XIAOPAW_OCR_TIMEOUT", "30"))

        try:
            images = convert_from_path(str(path), first_page=1, last_page=page_limit)
        except Exception as exc:
            logger.warning("OCR fallback: pdf2image conversion failed: %s", exc)
            return []

        page_bytes = []
        for img in images:
            import io

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            page_bytes.append(buf.getvalue())

        if not page_bytes:
            return []

        ocr = VisionOCR(page_limit=page_limit, timeout=timeout)
        texts = ocr.ocr_pages(page_bytes)

        sections: list[Section] = []
        for i, text in enumerate(texts, start=1):
            text = text.strip()
            if text:
                sections.append(Section(text=text, locator=f"page={i}"))
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

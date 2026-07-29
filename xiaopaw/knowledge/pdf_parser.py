"""Deep PDF parser using pdfplumber for text + table extraction.

Falls back to pypdf when pdfplumber is unavailable or the document
has sufficient text coverage from pypdf alone.
"""
from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Section:
    text: str
    locator: str = ""


@dataclass(frozen=True)
class ExtractResult:
    title: str
    sections: list[Section]


class DeepPdfParser:
    """Extract text + tables from PDF using pdfplumber.

    Three-level cascade:
    Level 1: pypdf pure text (existing)
    Level 2: pdfplumber text + tables (this parser)
    Level 3: OCR (handled by adapters.py cascade logic)
    """

    def __init__(self, *, text_coverage_threshold: float = 0.3):
        self._threshold = text_coverage_threshold

    def parse(self, path: Path, *, title: str = "") -> list[Section]:
        """Parse PDF, returning sections per page."""
        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber not installed, deep PDF parse unavailable")
            return []

        title = title or path.name
        sections: list[Section] = []
        total_chars = 0

        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                page_text = (page.extract_text() or "").strip()
                tables = page.extract_tables() or []

                # Build section content: text + tables
                parts = []
                if page_text:
                    parts.append(page_text)

                for table in tables:
                    md_table = self._table_to_markdown(table)
                    if md_table:
                        parts.append(md_table)

                content = "\n\n".join(parts)
                total_chars += len(content)

                if content:
                    sections.append(Section(text=content, locator=f"page={i}"))

        # Calculate text coverage ratio
        if not sections:
            return []

        # Estimate coverage: chars per page vs expected page size
        # If very low coverage, caller may want to trigger OCR
        logger.info(
            "deep PDF parse: %s → %d sections, %d chars",
            path.name,
            len(sections),
            total_chars,
        )
        return sections

    @staticmethod
    def _table_to_markdown(table: list[list]) -> str:
        """Convert pdfplumber table (list[list[str|None]]) to Markdown format."""
        if not table:
            return ""
        rows = [[str(cell or "").strip() for cell in row] for row in table]
        # Filter out completely empty rows
        rows = [r for r in rows if any(c for c in r)]
        if not rows:
            return ""

        ncols = max(len(r) for r in rows)
        # Pad rows to same length
        rows = [r + [""] * (ncols - len(r)) for r in rows]

        header = "| " + " | ".join(rows[0]) + " |"
        separator = "| " + " | ".join(["---"] * ncols) + " |"
        body = "\n".join("| " + " | ".join(r) + " |" for r in rows[1:])
        return f"\n{header}\n{separator}\n{body}\n"

    def text_coverage_ratio(self, path: Path) -> float:
        """Estimate what fraction of pages have meaningful text."""
        try:
            import pdfplumber
        except ImportError:
            return 0.0
        try:
            with pdfplumber.open(str(path)) as pdf:
                if not pdf.pages:
                    return 0.0
                text_pages = sum(
                    1
                    for p in pdf.pages
                    if len((p.extract_text() or "").strip()) > 50
                )
                return text_pages / len(pdf.pages)
        except Exception:
            return 0.0

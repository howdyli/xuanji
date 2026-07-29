"""Tests for deep PDF parser and three-level cascade in adapters."""
from __future__ import annotations

import os
import sys
import types
import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── pdf_parser tests ──────────────────────────────────────────────────────────

from xiaopaw.knowledge.pdf_parser import DeepPdfParser


class TestTableToMarkdown:
    def test_table_to_markdown(self):
        table = [
            ["Name", "Age"],
            ["Alice", "30"],
            ["Bob", "25"],
        ]
        result = DeepPdfParser._table_to_markdown(table)
        assert "| Name | Age |" in result
        assert "| --- | --- |" in result
        assert "| Alice | 30 |" in result
        assert "| Bob | 25 |" in result

    def test_table_to_markdown_empty(self):
        assert DeepPdfParser._table_to_markdown([]) == ""

    def test_table_to_markdown_none_cells(self):
        table = [
            ["A", None],
            [None, "B"],
        ]
        result = DeepPdfParser._table_to_markdown(table)
        assert "| A |" in result
        assert "| B |" in result

    def test_table_to_markdown_all_empty_rows(self):
        table = [
            [None, None],
            ["", ""],
        ]
        assert DeepPdfParser._table_to_markdown(table) == ""


class TestDeepPdfParserNoPdfplumber:
    def test_parse_returns_empty_when_no_pdfplumber(self, tmp_path: Path):
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        parser = DeepPdfParser()
        # Simulate pdfplumber not installed
        with patch.dict(sys.modules, {"pdfplumber": None}):
            result = parser.parse(fake_pdf)
        assert result == []

    def test_text_coverage_ratio_no_pdfplumber(self, tmp_path: Path):
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        parser = DeepPdfParser()
        with patch.dict(sys.modules, {"pdfplumber": None}):
            ratio = parser.text_coverage_ratio(fake_pdf)
        assert ratio == 0.0


class TestDeepPdfParserWithMock:
    def test_parse_with_mock_pdfplumber(self, tmp_path: Path):
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Hello world"
        mock_page.extract_tables.return_value = []

        mock_pdf_ctx = MagicMock()
        mock_pdf_ctx.__enter__ = MagicMock(return_value=MagicMock(pages=[mock_page]))
        mock_pdf_ctx.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf_ctx

        parser = DeepPdfParser()
        with patch.dict(sys.modules, {"pdfplumber": mock_pdfplumber}):
            sections = parser.parse(fake_pdf)

        assert len(sections) == 1
        assert sections[0].text == "Hello world"
        assert sections[0].locator == "page=1"


# ── adapters.py cascade tests ────────────────────────────────────────────────

from xiaopaw.knowledge.adapters import FileAdapter, Section, AdapterError


class TestExtractPdfDefaultPypdf:
    def test_default_uses_pypdf(self, tmp_path: Path):
        """Without XIAOPAW_DEEP_PDF_PARSE, should use pypdf."""
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "pypdf text"
        mock_reader.pages = [mock_page]

        with (
            patch.dict(os.environ, {}, clear=False),
            patch("pypdf.PdfReader", return_value=mock_reader),
        ):
            # Ensure deep parse is NOT enabled
            os.environ.pop("XIAOPAW_DEEP_PDF_PARSE", None)
            sections = FileAdapter._extract_pdf(fake_pdf)

        assert len(sections) == 1
        assert sections[0].text == "pypdf text"


class TestExtractPdfDeepEnabled:
    def test_deep_parse_enabled(self, tmp_path: Path):
        """With XIAOPAW_DEEP_PDF_PARSE=1, should try DeepPdfParser first."""
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        mock_section = Section(text="deep content", locator="page=1")

        with (
            patch.dict(os.environ, {"XIAOPAW_DEEP_PDF_PARSE": "1"}),
            patch(
                "xiaopaw.knowledge.pdf_parser.DeepPdfParser.parse",
                return_value=[mock_section],
            ),
        ):
            sections = FileAdapter._extract_pdf(fake_pdf)

        assert len(sections) == 1
        assert sections[0].text == "deep content"

    def test_deep_parse_fallback_to_pypdf(self, tmp_path: Path):
        """When deep parse returns empty, should fall back to pypdf."""
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "pypdf fallback"
        mock_reader.pages = [mock_page]

        with (
            patch.dict(os.environ, {"XIAOPAW_DEEP_PDF_PARSE": "1"}),
            patch(
                "xiaopaw.knowledge.pdf_parser.DeepPdfParser.parse",
                return_value=[],
            ),
            patch("pypdf.PdfReader", return_value=mock_reader),
        ):
            sections = FileAdapter._extract_pdf(fake_pdf)

        assert len(sections) == 1
        assert sections[0].text == "pypdf fallback"


class TestExtractPdfOcrFallback:
    def test_ocr_fallback_when_no_text(self, tmp_path: Path):
        """When pypdf returns no text and OCR is enabled, should try OCR."""
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_reader.pages = [mock_page]

        ocr_section = Section(text="ocr text", locator="page=1")

        with (
            patch.dict(
                os.environ,
                {"XIAOPAW_OCR_ENABLED": "1"},
                clear=False,
            ),
            patch("pypdf.PdfReader", return_value=mock_reader),
            patch.object(
                FileAdapter,
                "_ocr_fallback",
                return_value=[ocr_section],
            ),
        ):
            os.environ.pop("XIAOPAW_DEEP_PDF_PARSE", None)
            sections = FileAdapter._extract_pdf(fake_pdf)

        assert len(sections) == 1
        assert sections[0].text == "ocr text"

    def test_raises_when_all_levels_fail(self, tmp_path: Path):
        """When all levels fail, should raise AdapterError."""
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_reader.pages = [mock_page]

        with (
            patch("pypdf.PdfReader", return_value=mock_reader),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("XIAOPAW_DEEP_PDF_PARSE", None)
            os.environ.pop("XIAOPAW_OCR_ENABLED", None)
            with pytest.raises(AdapterError, match="no extractable text"):
                FileAdapter._extract_pdf(fake_pdf)

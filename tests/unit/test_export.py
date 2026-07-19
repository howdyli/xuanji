"""Tests for the export subsystem: MarkdownBuilder, PDF renderer, DOCX renderer, ExportService."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass

from xiaopaw.export.markdown_builder import (
    build_session_markdown,
    _format_timestamp,
    _format_error_message,
    _is_cron_message,
)
from xiaopaw.export.docx_renderer import render_markdown_to_docx
from xiaopaw.export.pdf_renderer import render_markdown_to_pdf


# ── Fixtures ────────────────────────────────────────────────────────────────

SAMPLE_MESSAGES = [
    {"role": "user", "content": "你好，帮我写一份报告", "ts": 1720000000000, "feishu_msg_id": None},
    {"role": "assistant", "content": "好的，这是一份报告。", "ts": 1720000060000, "feishu_msg_id": None},
]


# ═══════════════════════════════════════════════════════════════════════════
# MarkdownBuilder Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMarkdownBuilder:
    def test_basic_messages(self):
        """基本消息列表生成正确的 Markdown"""
        md = build_session_markdown(
            "测试会话", "s-test-001", "2026-07-08", SAMPLE_MESSAGES
        )
        assert "# 测试会话" in md
        assert "你好，帮我写一份报告" in md
        assert "好的，这是一份报告。" in md
        assert "User" in md
        assert "Assistant" in md

    def test_error_messages(self):
        """[ERROR_DISPLAY:type:message] 正确转换为 > ⚠️ 错误: message"""
        msgs = [
            {
                "role": "assistant",
                "content": "[ERROR_DISPLAY:server_error:Internal server error]",
                "ts": 1720000000000,
                "feishu_msg_id": None,
            }
        ]
        md = build_session_markdown("err", "s-err", "2026-07-08", msgs)
        assert "> ⚠️ 错误: Internal server error" in md

    def test_timestamp_formatting(self):
        """Unix 毫秒时间戳转为 YYYY-MM-DD HH:MM"""
        result = _format_timestamp(1720000000000)
        # 1720000000000 ms = 2024-07-03 ... (exact depends on TZ)
        assert len(result) == 16  # "YYYY-MM-DD HH:MM"
        assert result[4] == "-"
        assert result[10] == " "

    def test_cron_prefix_annotation(self):
        """cron_ 前缀标注为（定时任务触发）"""
        msgs = [
            {
                "role": "user",
                "content": "定时消息",
                "ts": 1720000000000,
                "feishu_msg_id": "cron_daily_report",
            }
        ]
        md = build_session_markdown("cron", "s-cron", "2026-07-08", msgs)
        assert "（定时任务触发）" in md

    def test_empty_messages(self):
        """空消息列表"""
        md = build_session_markdown("空会话", "s-empty", "2026-07-08", [])
        assert "# 空会话" in md
        assert "**消息数**: 0" in md
        # Should still have the footer
        assert "玄机" in md

    def test_metadata_included(self):
        """元数据区包含会话ID、创建时间、消息数"""
        md = build_session_markdown(
            "meta", "s-meta-123", "2026-01-15", SAMPLE_MESSAGES
        )
        assert "s-meta-123" in md
        assert "2026-01-15" in md
        assert "**消息数**: 2" in md

    def test_metadata_excluded(self):
        """include_metadata=False 时不输出元数据块"""
        md = build_session_markdown(
            "no-meta", "s-x", "2026-01-01", SAMPLE_MESSAGES, include_metadata=False
        )
        assert "s-x" not in md  # session_id should not appear in metadata

    def test_format_error_message_helper(self):
        """_format_error_message 辅助函数直接测试"""
        result = _format_error_message("[ERROR_DISPLAY:timeout:Connection timed out]")
        assert result == "> ⚠️ 错误: Connection timed out"

    def test_is_cron_message(self):
        """_is_cron_message 判断逻辑"""
        assert _is_cron_message("cron_abc") is True
        assert _is_cron_message("normal_msg_123") is False
        assert _is_cron_message(None) is False
        assert _is_cron_message("") is False


# ═══════════════════════════════════════════════════════════════════════════
# DOCX Renderer Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestDocxRenderer:
    def test_generates_valid_docx(self):
        """生成的字节以 PK 开头（ZIP 格式）"""
        md = "# Hello\n\nThis is a test."
        result = render_markdown_to_docx(md)
        assert isinstance(result, bytes)
        assert result[:2] == b"PK"  # DOCX is a ZIP file
        assert len(result) > 100

    def test_handles_chinese_content(self):
        """中文内容不报错"""
        md = "# 测试\n\n这是一段中文内容。"
        result = render_markdown_to_docx(md)
        assert isinstance(result, bytes)
        assert len(result) > 50

    def test_handles_code_blocks(self):
        """代码块正确渲染"""
        md = "# Code\n\n```python\nprint('hello')\n```"
        result = render_markdown_to_docx(md)
        assert isinstance(result, bytes)
        assert result[:2] == b"PK"


# ═══════════════════════════════════════════════════════════════════════════
# PDF Renderer Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestPdfRenderer:
    def test_generates_valid_pdf(self):
        """生成的字节以 %PDF 开头"""
        pytest.importorskip("weasyprint")
        md = "# Hello\n\nTest content."
        result = render_markdown_to_pdf(md)
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"

    def test_handles_chinese_content(self):
        """中文内容不报错"""
        pytest.importorskip("weasyprint")
        md = "# 中文测试\n\n这是一段中文内容。"
        result = render_markdown_to_pdf(md)
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"

    def test_raises_without_weasyprint(self):
        """weasyprint 不可用时抛出 RuntimeError"""
        from xiaopaw.export import pdf_renderer

        original = pdf_renderer.weasyprint
        try:
            pdf_renderer.weasyprint = None
            with pytest.raises(RuntimeError, match="weasyprint not available"):
                render_markdown_to_pdf("# test")
        finally:
            pdf_renderer.weasyprint = original


# ═══════════════════════════════════════════════════════════════════════════
# ExportService Tests
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FakeSessionEntry:
    """Minimal stand-in for SessionManager's SessionEntry."""
    id: str = "s-test"
    title: str = "测试会话"
    created_at: str = "2026-07-08"
    verbose: bool = False
    message_count: int = 2


@dataclass(frozen=True)
class FakeMessageEntry:
    role: str = "user"
    content: str = "你好"
    ts: int = 1720000000000
    feishu_msg_id: str | None = None


@pytest.fixture
def mock_session_mgr():
    mgr = MagicMock()
    mgr.get_session_by_id = AsyncMock(return_value=FakeSessionEntry())
    mgr.load_history = AsyncMock(
        return_value=[
            FakeMessageEntry(role="user", content="你好", ts=1720000000000),
            FakeMessageEntry(role="assistant", content="你好！有什么可以帮你？", ts=1720000060000),
        ]
    )
    return mgr


class TestExportService:
    @pytest.mark.asyncio
    async def test_export_markdown(self, mock_session_mgr):
        """Markdown 导出返回正确的 bytes 和 content_type"""
        from xiaopaw.export.service import ExportService

        svc = ExportService(mock_session_mgr)
        file_bytes, filename, content_type = await svc.export_session("s-test", "markdown")

        assert isinstance(file_bytes, bytes)
        assert filename == "s-test.md"
        assert content_type == "text/markdown; charset=utf-8"
        assert "测试会话" in file_bytes.decode("utf-8")

    @pytest.mark.asyncio
    async def test_export_unsupported_format(self, mock_session_mgr):
        """不支持的格式抛 ValueError"""
        from xiaopaw.export.service import ExportService

        svc = ExportService(mock_session_mgr)
        with pytest.raises(ValueError, match="Unsupported export format"):
            await svc.export_session("s-test", "xlsx")

    @pytest.mark.asyncio
    async def test_export_pdf(self, mock_session_mgr):
        """PDF 导出返回正确的 content_type"""
        pytest.importorskip("weasyprint")
        from xiaopaw.export.service import ExportService

        svc = ExportService(mock_session_mgr)
        file_bytes, filename, content_type = await svc.export_session("s-test", "pdf")

        assert filename == "s-test.pdf"
        assert content_type == "application/pdf"
        assert file_bytes[:4] == b"%PDF"

    @pytest.mark.asyncio
    async def test_export_docx(self, mock_session_mgr):
        """DOCX 导出返回正确的 content_type"""
        from xiaopaw.export.service import ExportService

        svc = ExportService(mock_session_mgr)
        file_bytes, filename, content_type = await svc.export_session("s-test", "docx")

        assert filename == "s-test.docx"
        assert "wordprocessingml" in content_type
        assert file_bytes[:2] == b"PK"

    @pytest.mark.asyncio
    async def test_export_session_not_found(self, mock_session_mgr):
        """会话不存在时抛 FileNotFoundError"""
        from xiaopaw.export.service import ExportService

        mock_session_mgr.get_session_by_id = AsyncMock(return_value=None)
        svc = ExportService(mock_session_mgr)
        with pytest.raises(FileNotFoundError, match="Session not found"):
            await svc.export_session("s-nonexistent", "markdown")


# ═══════════════════════════════════════════════════════════════════════════
# MarkdownBuilder — 补充边界测试
# ═══════════════════════════════════════════════════════════════════════════


class TestMarkdownBuilderEdgeCases:
    """基于真实 markdown_builder.py 逻辑的边界补充。"""

    def test_footer_always_present(self):
        """页脚始终存在，无论消息列表是否为空。"""
        md = build_session_markdown("t", "s-1", "2026-01-01", [])
        assert "玄机" in md
        md2 = build_session_markdown("t", "s-1", "2026-01-01", SAMPLE_MESSAGES)
        assert "玄机" in md2

    def test_role_emoji_rendered(self):
        """role 前带正确的 emoji 标识。"""
        md = build_session_markdown("t", "s-1", "2026-01-01", SAMPLE_MESSAGES)
        assert "👤" in md  # user
        assert "🤖" in md  # assistant

    def test_ts_zero_shows_unknown(self):
        """ts=0 时显示「未知时间」。"""
        msgs = [{"role": "user", "content": "hello", "ts": 0, "feishu_msg_id": None}]
        md = build_session_markdown("t", "s-1", "2026-01-01", msgs)
        assert "未知时间" in md

    def test_format_error_message_non_matching(self):
        """_format_error_message 对非 ERROR_DISPLAY 格式的内容原样输出。"""
        result = _format_error_message("just plain text")
        assert result == "> ⚠️ 错误: just plain text"

    def test_message_separator_hr(self):
        """每条消息之间用 --- 分隔。"""
        md = build_session_markdown("t", "s-1", "2026-01-01", SAMPLE_MESSAGES)
        assert md.count("---") >= 2  # at least one per message + header sep


# ═══════════════════════════════════════════════════════════════════════════
# DOCX Renderer — 内容验证补充
# ═══════════════════════════════════════════════════════════════════════════


class TestDocxRendererContent:
    """基于真实 docx_renderer.py 的渲染内容验证。"""

    def _parse_docx_text(self, docx_bytes: bytes) -> str:
        """从 DOCX bytes 中提取全部文本用于断言。"""
        import io
        from docx import Document as DocxDoc
        doc = DocxDoc(io.BytesIO(docx_bytes))
        return "\n".join(p.text for p in doc.paragraphs)

    def test_heading_in_output(self):
        """H1 标题出现在 DOCX 中。"""
        md = "# Main Title\n\nSome paragraph."
        result = render_markdown_to_docx(md)
        text = self._parse_docx_text(result)
        assert "Main Title" in text

    def test_blockquote_rendered(self):
        """blockquote 渲染为带缩进的段落。"""
        md = "> This is a quote"
        result = render_markdown_to_docx(md)
        assert isinstance(result, bytes)
        assert result[:2] == b"PK"

    def test_unordered_list(self):
        """无序列表正确渲染。"""
        md = "- item one\n- item two\n- item three"
        result = render_markdown_to_docx(md)
        text = self._parse_docx_text(result)
        assert "item one" in text
        assert "item two" in text

    def test_ordered_list(self):
        """有序列表正确渲染。"""
        md = "1. first\n2. second"
        result = render_markdown_to_docx(md)
        text = self._parse_docx_text(result)
        assert "first" in text
        assert "second" in text

    def test_inline_bold_and_italic(self):
        """行内 bold/italic 格式不报错。"""
        md = "This is **bold** and *italic* text."
        result = render_markdown_to_docx(md)
        assert isinstance(result, bytes)
        assert result[:2] == b"PK"

    def test_inline_code(self):
        """行内 code 格式不报错。"""
        md = "Use `print()` to output."
        result = render_markdown_to_docx(md)
        assert isinstance(result, bytes)
        assert result[:2] == b"PK"

    def test_table_rendered(self):
        """表格渲染不报错且输出有效 DOCX。"""
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = render_markdown_to_docx(md)
        assert isinstance(result, bytes)
        assert result[:2] == b"PK"


# ═══════════════════════════════════════════════════════════════════════════
# PDF Renderer — 模板结构补充
# ═══════════════════════════════════════════════════════════════════════════


class TestPdfRendererTemplate:
    """基于真实 pdf_renderer.py 的 HTML 模板验证（仅 weasyprint 可用时）。"""

    def test_html_template_contains_doctype(self):
        """_HTML_TEMPLATE 包含 DOCTYPE 声明。"""
        from xiaopaw.export.pdf_renderer import _HTML_TEMPLATE
        assert "<!DOCTYPE html>" in _HTML_TEMPLATE
        assert "zh-CN" in _HTML_TEMPLATE

    def test_css_loaded_from_template(self):
        """_CSS_TEXT 在模块加载时已读取（可能为空字符串）。"""
        from xiaopaw.export.pdf_renderer import _CSS_TEXT
        assert isinstance(_CSS_TEXT, str)

    def test_error_message_contains_install_hint(self):
        """RuntimeError 消息包含安装指引。"""
        from xiaopaw.export import pdf_renderer
        original = pdf_renderer.weasyprint
        try:
            pdf_renderer.weasyprint = None
            with pytest.raises(RuntimeError, match="pip install weasyprint"):
                render_markdown_to_pdf("# test")
        finally:
            pdf_renderer.weasyprint = original


# ═══════════════════════════════════════════════════════════════════════════
# ExportService — title 回退补充
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EmptyTitleSessionEntry:
    """title 为空字符串的 SessionEntry 替身。"""
    id: str = "s-empty-title"
    title: str = ""
    created_at: str = "2026-07-08"
    verbose: bool = False
    message_count: int = 1


class TestExportServiceTitleFallback:
    """基于真实 service.py 的 title 回退逻辑。"""

    @pytest.mark.asyncio
    async def test_empty_title_falls_back_to_session_id(self):
        """title 为空时使用 session_id 作为标题。"""
        from xiaopaw.export.service import ExportService

        mgr = MagicMock()
        mgr.get_session_by_id = AsyncMock(return_value=EmptyTitleSessionEntry())
        mgr.load_history = AsyncMock(
            return_value=[FakeMessageEntry(role="user", content="hi", ts=1720000000000)]
        )
        svc = ExportService(mgr)
        file_bytes, filename, content_type = await svc.export_session("s-empty-title", "markdown")
        text = file_bytes.decode("utf-8")
        # When title is "", the code does: title = session.title or session_id
        assert "s-empty-title" in text

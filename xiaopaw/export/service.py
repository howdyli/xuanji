"""Export service: compose MarkdownBuilder + renderers into a full export pipeline."""

from __future__ import annotations

import logging
from dataclasses import asdict

from xiaopaw.export.markdown_builder import build_session_markdown
from xiaopaw.export.pdf_renderer import render_markdown_to_pdf
from xiaopaw.export.docx_renderer import render_markdown_to_docx
from xiaopaw.session.manager import SessionManager

logger = logging.getLogger(__name__)

_SUPPORTED_FORMATS = ("markdown", "pdf", "docx")

_CONTENT_TYPES = {
    "markdown": "text/markdown; charset=utf-8",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_EXTENSIONS = {"markdown": ".md", "pdf": ".pdf", "docx": ".docx"}


class ExportService:
    """Combine MarkdownBuilder + renderers to export a session."""

    def __init__(self, session_mgr: SessionManager) -> None:
        self._session_mgr = session_mgr

    async def export_session(
        self, session_id: str, fmt: str
    ) -> tuple[bytes, str, str]:
        """Export a session to the requested format.

        Returns
        -------
        (file_bytes, filename, content_type)

        Raises
        ------
        ValueError  – unsupported format
        FileNotFoundError – session_id not found
        """
        if fmt not in _SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported export format: {fmt!r}. "
                f"Use one of: {', '.join(_SUPPORTED_FORMATS)}"
            )

        # 1. Load session metadata
        session = await self._session_mgr.get_session_by_id(session_id)
        if session is None:
            raise FileNotFoundError(f"Session not found: {session_id}")

        title = session.title or session_id
        created_at = session.created_at

        # 2. Load full message history (99999 turns ≈ all)
        entries = await self._session_mgr.load_history(session_id, max_turns=99999)

        # Convert MessageEntry dataclass list → plain dicts for MarkdownBuilder
        messages = [asdict(e) for e in entries]

        # 3. Build Markdown intermediate representation
        md_text = build_session_markdown(title, session_id, created_at, messages)

        # 4. Render to the target format
        if fmt == "markdown":
            file_bytes = md_text.encode("utf-8")
        elif fmt == "pdf":
            file_bytes = render_markdown_to_pdf(md_text)
        else:  # docx
            file_bytes = render_markdown_to_docx(md_text)

        filename = f"{session_id}{_EXTENSIONS[fmt]}"
        content_type = _CONTENT_TYPES[fmt]

        logger.info(
            "export: session=%s fmt=%s size=%d bytes", session_id, fmt, len(file_bytes)
        )
        return file_bytes, filename, content_type

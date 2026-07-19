"""PDF renderer — converts Markdown text to a high-quality PDF byte stream.

Uses ``markdown`` for MD→HTML conversion and ``weasyprint`` for HTML→PDF.
If weasyprint (or its system dependencies) is unavailable, a clear
``RuntimeError`` is raised with installation instructions.
"""

from __future__ import annotations

from pathlib import Path

import markdown

# Graceful degradation: weasyprint requires system-level libs (cairo, pango, gobject).
try:
    import weasyprint
except (ImportError, OSError):
    weasyprint = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Load embedded CSS once at module level
# ---------------------------------------------------------------------------
_CSS_PATH = Path(__file__).parent / "templates" / "export.css"
_CSS_TEXT: str = _CSS_PATH.read_text(encoding="utf-8") if _CSS_PATH.exists() else ""

# ---------------------------------------------------------------------------
# HTML document template
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
{css}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def render_markdown_to_pdf(markdown_text: str) -> bytes:
    """Render *markdown_text* to a PDF byte stream.

    Parameters
    ----------
    markdown_text : str
        Markdown-formatted session content (output of
        :func:`xiaopaw.export.markdown_builder.build_session_markdown`).

    Returns
    -------
    bytes
        A valid PDF document (starts with ``%PDF``).

    Raises
    ------
    RuntimeError
        If weasyprint is not available.
    """
    if weasyprint is None:
        raise RuntimeError(
            "weasyprint not available. "
            "Install system deps (cairo, pango, gobject) first, then:\n"
            "    pip install weasyprint\n"
            "macOS: brew install pango\n"
            "Linux: sudo apt install libpango1.0-dev libcairo2-dev libgdk-pixbuf2.0-dev"
        )

    # 1. Markdown → HTML fragment
    html_body = markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "codehilite", "nl2br"],
        extension_configs={
            "codehilite": {"css_class": "codehilite", "guess_lang": False},
        },
    )

    # 2. Wrap in full HTML document with inline CSS
    full_html = _HTML_TEMPLATE.format(css=_CSS_TEXT, body=html_body)

    # 3. HTML → PDF bytes
    pdf_bytes: bytes = weasyprint.HTML(string=full_html).write_pdf()
    return pdf_bytes

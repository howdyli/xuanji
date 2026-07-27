"""HTML renderer — converts Markdown text to a standalone HTML document.

Reuses the same Markdown pipeline and stylesheet as the PDF renderer so the
in-browser preview matches the printed output. Zero extra dependencies.
"""

from __future__ import annotations

import markdown

# Shared template/CSS with the PDF renderer keeps preview and print identical.
from xiaopaw.export.pdf_renderer import _CSS_TEXT, _HTML_TEMPLATE


def render_markdown_to_html(markdown_text: str) -> bytes:
    """Render *markdown_text* to a self-contained HTML document (UTF-8 bytes).

    Parameters
    ----------
    markdown_text : str
        Markdown-formatted session content (output of
        :func:`xiaopaw.export.markdown_builder.build_session_markdown`).

    Returns
    -------
    bytes
        A complete HTML document with inline CSS, ready to open in a browser.
    """
    html_body = markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "codehilite", "nl2br"],
        extension_configs={
            "codehilite": {"css_class": "codehilite", "guess_lang": False},
        },
    )
    full_html = _HTML_TEMPLATE.format(css=_CSS_TEXT, body=html_body)
    return full_html.encode("utf-8")

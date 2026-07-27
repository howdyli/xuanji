"""Export route handler: GET /api/frontend/sessions/{session_id}/export"""

from __future__ import annotations

import logging

from aiohttp import web

from xiaopaw.export.service import ExportService
from xiaopaw.frontend.routes.helpers import check_auth

logger = logging.getLogger(__name__)


async def handle_export_session(request: web.Request) -> web.StreamResponse:
    """GET /api/frontend/sessions/{session_id}/export?format=pdf|markdown|docx|pptx|html"""
    # 1. Auth
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    # 2. Parameters
    session_id = request.match_info["session_id"]
    fmt = request.query.get("format", "markdown")

    # 3. Validate format
    if fmt not in ("markdown", "pdf", "docx", "pptx", "html"):
        return web.json_response(
            {
                "error": f"Unsupported format: {fmt!r}. "
                "Use markdown, pdf, docx, pptx, or html."
            },
            status=400,
        )

    # 4. Call ExportService
    export_service: ExportService | None = request.app.get("export_service")
    if export_service is None:
        return web.json_response({"error": "export not available"}, status=503)

    try:
        file_bytes, filename, content_type = await export_service.export_session(
            session_id, fmt
        )
    except FileNotFoundError:
        return web.json_response({"error": "Session not found"}, status=404)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.error("Export failed for session %s: %s", session_id, exc, exc_info=True)
        return web.json_response({"error": "Export failed"}, status=500)

    # 5. Stream file back to the client
    response = web.StreamResponse()
    response.headers["Content-Type"] = content_type
    # HTML is meant for in-browser preview; everything else downloads.
    disposition = "inline" if fmt == "html" else "attachment"
    response.headers["Content-Disposition"] = (
        f'{disposition}; filename="{filename}"'
    )
    response.headers["Content-Length"] = str(len(file_bytes))
    await response.prepare(request)
    await response.write(file_bytes)
    await response.write_eof()
    return response


def register_export_routes(
    app: web.Application, export_service: ExportService | None = None
) -> None:
    """Register export routes on the aiohttp application.

    If *export_service* is provided it is stored on ``app``; otherwise the
    handler reads ``app["export_service"]`` which must have been set earlier.
    """
    if export_service is not None:
        app["export_service"] = export_service
    app.router.add_get(
        "/api/frontend/sessions/{session_id}/export", handle_export_session
    )

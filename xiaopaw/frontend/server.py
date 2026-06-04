"""Frontend aiohttp server: serve static files + REST API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from xiaopaw.frontend.api import register_routes
from xiaopaw.skills_mgmt.api import register_routes as register_skills_routes
from xiaopaw.skills_mgmt.market import MarketRegistry, MarketSync
from xiaopaw.skills_mgmt.packager import DEFAULT_MAX_ARCHIVE_BYTES
from xiaopaw.skills_mgmt.registry import SkillRegistry

logger = logging.getLogger(__name__)


def _get_frontend_dir() -> Path | None:
    """Look for built frontend assets in several locations."""
    candidates = [
        Path(__file__).parent.parent.parent / "frontend" / "build",
        Path(__file__).parent.parent.parent / "frontend" / "dist",
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            return p
    return None


def create_frontend_app(
    runner: Any = None,
    sender: Any = None,
    session_mgr: Any = None,
    pg_store: Any = None,
    token: str = "",
    skill_registry: SkillRegistry | None = None,
    skills_max_upload_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    market_registry: MarketRegistry | None = None,
    market_sync: MarketSync | None = None,
    workspace_dir: str | None = None,
    user_auth: Any = None,
    expert_registry: Any = None,
    automation_registry: Any = None,
    channel_manager: Any = None,
) -> web.Application:
    """Create the aiohttp Application serving both API and static files."""
    app = web.Application(client_max_size=max(skills_max_upload_bytes, 5 * 1024 * 1024) + 1024 * 1024)

    # Store shared dependencies
    app["runner"] = runner
    app["sender"] = sender
    app["session_mgr"] = session_mgr
    app["pg_store"] = pg_store
    app["frontend_token"] = token
    app["skill_registry"] = skill_registry
    app["skills_max_upload_bytes"] = skills_max_upload_bytes
    app["market_registry"] = market_registry
    app["market_sync"] = market_sync
    app["workspace_dir"] = workspace_dir or ""
    app["user_auth"] = user_auth
    app["expert_registry"] = expert_registry
    app["automation_registry"] = automation_registry
    app["channel_manager"] = channel_manager

    # Register REST API routes
    register_routes(app)
    register_skills_routes(app)

    # Serve built frontend static files
    frontend_dir = _get_frontend_dir()
    if frontend_dir:
        # Serve static assets (JS, CSS, images) from /assets/
        static_path = frontend_dir / "assets"
        if static_path.exists():
            app.router.add_static("/assets", str(static_path), name="assets")

        # Serve root-level static files (logos, favicons, etc.)
        for static_file in frontend_dir.iterdir():
            if static_file.is_file() and static_file.name != "index.html":
                app.router.add_get(
                    f"/{static_file.name}",
                    lambda req, fp=static_file: web.FileResponse(str(fp)),
                )

        # Serve index.html for SPA routes
        index_path = frontend_dir / "index.html"
        if index_path.exists():

            async def _serve_index(request: web.Request) -> web.FileResponse:
                return web.FileResponse(str(index_path))

            app.router.add_get("/", _serve_index, name="index")
            # Catch-all for SPA client-side routing (except API routes)
            app.router.add_get("/{tail:.*}", _serve_index, name="spa_fallback")

        logger.info("frontend: serving static files from %s", frontend_dir)
    else:
        logger.warning("frontend: no built assets found (run 'npm run build' in frontend/)")

    return app

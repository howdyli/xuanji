"""Frontend route modules — unified registration entry point."""

from __future__ import annotations

from aiohttp import web

from xiaopaw.frontend.routes.auth import register_auth_routes
from xiaopaw.frontend.routes.workspace import register_workspace_routes
from xiaopaw.frontend.routes.session import register_session_routes
from xiaopaw.frontend.routes.expert import register_expert_routes
from xiaopaw.frontend.routes.scenario import register_scenario_routes
from xiaopaw.frontend.routes.automation import register_automation_routes
from xiaopaw.frontend.routes.channel import register_channel_routes
from xiaopaw.frontend.routes.library import register_library_routes
from xiaopaw.frontend.routes.export import register_export_routes
from xiaopaw.frontend.routes.search import register_search_routes
from xiaopaw.frontend.routes.activity import register_activity_routes
from xiaopaw.frontend.routes.activity_stream import register_activity_stream_routes
from xiaopaw.frontend.routes.team import register_team_routes
from xiaopaw.frontend.routes.notifications import register_notification_routes


def register_all_routes(app: web.Application) -> None:
    """Register all frontend API routes from modular sub-packages."""
    register_auth_routes(app)
    register_workspace_routes(app)
    register_session_routes(app)
    register_expert_routes(app)
    register_scenario_routes(app)
    register_automation_routes(app)
    register_channel_routes(app)
    register_library_routes(app)
    register_export_routes(app)
    register_search_routes(app)
    register_activity_routes(app)
    register_activity_stream_routes(app)
    register_team_routes(app)
    register_notification_routes(app)

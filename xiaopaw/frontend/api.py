"""REST API endpoints for the frontend.

This module is now a thin proxy that delegates to ``xiaopaw.frontend.routes.*``
sub-packages. Kept for backward compatibility — new code should import from
the route modules directly.
"""

from __future__ import annotations

from aiohttp import web

from xiaopaw.frontend.routes import register_all_routes

# Re-export handler names for any external imports that reference this module.
from xiaopaw.frontend.routes.auth import (
    handle_auth_register,
    handle_auth_login,
    handle_auth_logout,
    handle_auth_me,
    handle_auth_update_profile,
    handle_auth_change_password,
)
from xiaopaw.frontend.routes.workspace import (
    handle_file_download,
    handle_workspace_tree,
    handle_workspace_read,
    handle_workspace_write,
)
from xiaopaw.frontend.routes.session import (
    handle_message,
    handle_sessions,
    handle_session_messages,
    handle_config,
)
from xiaopaw.frontend.routes.expert import (
    handle_experts_list,
    handle_experts_categories,
    handle_expert_detail,
    handle_expert_create,
    handle_expert_update,
    handle_expert_delete,
)
from xiaopaw.frontend.routes.automation import (
    handle_automation_tasks_list,
    handle_automation_task_create,
    handle_automation_task_update,
    handle_automation_task_delete,
    handle_automation_task_toggle,
    handle_automation_templates,
)
from xiaopaw.frontend.routes.channel import (
    handle_channels_list,
    handle_channel_create,
    handle_channel_update,
    handle_channel_delete,
    handle_channel_test,
    handle_channel_fetch_models,
    handle_channels_health,
)
from xiaopaw.frontend.routes.library import (
    handle_library_files,
    handle_library_favorites_get,
    handle_library_favorites_update,
)
from xiaopaw.frontend.routes.export import handle_export_session
from xiaopaw.frontend.routes.search import handle_search


def register_routes(app: web.Application) -> None:
    """Register frontend API routes (backward-compatible entry point)."""
    register_all_routes(app)

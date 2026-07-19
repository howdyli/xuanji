"""Automation task CRUD route handlers."""

from __future__ import annotations

import logging

from aiohttp import web

from xiaopaw.frontend.routes.helpers import check_auth

logger = logging.getLogger(__name__)


async def handle_automation_tasks_list(request: web.Request) -> web.Response:
    """GET /api/frontend/automation/tasks — list all tasks."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("automation_registry")
    if not registry:
        return web.json_response({"tasks": [], "total": 0})
    tasks = registry.list_tasks()
    return web.json_response({"tasks": tasks, "total": len(tasks)})


async def handle_automation_task_create(request: web.Request) -> web.Response:
    """POST /api/frontend/automation/tasks — create task (supports from_template)."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("automation_registry")
    if not registry:
        return web.json_response({"error": "automation_registry unavailable"}, status=503)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=422)
    try:
        template_name = body.get("from_template", "").strip()
        if template_name:
            task = registry.create_from_template(template_name, body.get("overrides"))
        else:
            task = registry.create_task(body)
        return web.json_response(task, status=201)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def handle_automation_task_update(request: web.Request) -> web.Response:
    """PUT /api/frontend/automation/tasks/{id} — update a task."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("automation_registry")
    if not registry:
        return web.json_response({"error": "automation_registry unavailable"}, status=503)
    task_id = request.match_info.get("id", "")
    try:
        body = await request.json()
        task = registry.update_task(task_id, body)
        if not task:
            return web.json_response({"error": "not_found"}, status=404)
        return web.json_response(task)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def handle_automation_task_delete(request: web.Request) -> web.Response:
    """DELETE /api/frontend/automation/tasks/{id} — delete a task."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("automation_registry")
    if not registry:
        return web.json_response({"error": "automation_registry unavailable"}, status=503)
    task_id = request.match_info.get("id", "")
    if registry.delete_task(task_id):
        return web.json_response({"success": True})
    return web.json_response({"error": "not_found"}, status=404)


async def handle_automation_task_toggle(request: web.Request) -> web.Response:
    """PATCH /api/frontend/automation/tasks/{id}/toggle — enable/disable."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("automation_registry")
    if not registry:
        return web.json_response({"error": "automation_registry unavailable"}, status=503)
    task_id = request.match_info.get("id", "")
    task = registry.toggle_task(task_id)
    if not task:
        return web.json_response({"error": "not_found"}, status=404)
    return web.json_response(task)


async def handle_automation_templates(request: web.Request) -> web.Response:
    """GET /api/frontend/automation/templates — list preset templates."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("automation_registry")
    if not registry:
        return web.json_response({"templates": []})
    return web.json_response({"templates": registry.list_templates()})


def register_automation_routes(app: web.Application) -> None:
    """Register automation task routes."""
    app.router.add_get("/api/frontend/automation/tasks", handle_automation_tasks_list)
    app.router.add_post("/api/frontend/automation/tasks", handle_automation_task_create)
    app.router.add_put("/api/frontend/automation/tasks/{id}", handle_automation_task_update)
    app.router.add_delete("/api/frontend/automation/tasks/{id}", handle_automation_task_delete)
    app.router.add_patch("/api/frontend/automation/tasks/{id}/toggle", handle_automation_task_toggle)
    app.router.add_get("/api/frontend/automation/templates", handle_automation_templates)

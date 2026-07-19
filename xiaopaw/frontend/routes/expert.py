"""Expert CRUD route handlers."""

from __future__ import annotations

import logging

from aiohttp import web

from xiaopaw.frontend.routes.helpers import check_auth

logger = logging.getLogger(__name__)


async def handle_experts_list(request: web.Request) -> web.Response:
    """GET /api/frontend/experts — list all experts."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("expert_registry")
    if not registry:
        return web.json_response({"experts": []})
    return web.json_response({"experts": registry.list_all()})


async def handle_experts_categories(request: web.Request) -> web.Response:
    """GET /api/frontend/experts/categories — list expert categories."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("expert_registry")
    if not registry:
        return web.json_response({"categories": []})
    return web.json_response({"categories": registry.list_categories()})


async def handle_expert_detail(request: web.Request) -> web.Response:
    """GET /api/frontend/experts/{name} — get expert details."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("expert_registry")
    if not registry:
        return web.json_response({"error": "expert_registry unavailable"}, status=503)
    name = request.match_info.get("name", "")
    expert = registry.get(name)
    if not expert:
        return web.json_response({"error": "not_found"}, status=404)
    return web.json_response(expert)


async def handle_expert_create(request: web.Request) -> web.Response:
    """POST /api/frontend/experts — create a new expert."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("expert_registry")
    if not registry:
        return web.json_response({"error": "expert_registry unavailable"}, status=503)
    try:
        body = await request.json()
        expert = registry.create(body)
        return web.json_response(expert, status=201)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def handle_expert_update(request: web.Request) -> web.Response:
    """PUT /api/frontend/experts/{name} — update an expert."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("expert_registry")
    if not registry:
        return web.json_response({"error": "expert_registry unavailable"}, status=503)
    name = request.match_info.get("name", "")
    try:
        body = await request.json()
        expert = registry.update(name, body)
        if not expert:
            return web.json_response({"error": "not_found"}, status=404)
        return web.json_response(expert)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def handle_expert_delete(request: web.Request) -> web.Response:
    """DELETE /api/frontend/experts/{name} — delete an expert."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("expert_registry")
    if not registry:
        return web.json_response({"error": "expert_registry unavailable"}, status=503)
    name = request.match_info.get("name", "")
    if registry.delete(name):
        return web.json_response({"success": True})
    return web.json_response({"error": "not_found"}, status=404)


def register_expert_routes(app: web.Application) -> None:
    """Register expert CRUD routes."""
    app.router.add_get("/api/frontend/experts", handle_experts_list)
    app.router.add_get("/api/frontend/experts/categories", handle_experts_categories)
    app.router.add_get("/api/frontend/experts/{name}", handle_expert_detail)
    app.router.add_post("/api/frontend/experts", handle_expert_create)
    app.router.add_put("/api/frontend/experts/{name}", handle_expert_update)
    app.router.add_delete("/api/frontend/experts/{name}", handle_expert_delete)

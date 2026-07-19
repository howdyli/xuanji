"""LLM channel management route handlers."""

from __future__ import annotations

import logging

from aiohttp import web

from xiaopaw.frontend.routes.helpers import check_auth, mask_key_display

logger = logging.getLogger(__name__)


def _get_channel_mgr(request: web.Request):
    """Helper to get channel_manager from app."""
    return request.app.get("channel_manager")


async def handle_channels_list(request: web.Request) -> web.Response:
    """GET /api/frontend/channels — list all LLM channels."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    mgr = _get_channel_mgr(request)
    if not mgr:
        return web.json_response({"channels": []})

    channels = []
    for ch in mgr.list_channels():
        channels.append({
            "name": ch.name,
            "base_url": ch.base_url,
            "provider": ch.provider,
            "models": ch.models,
            "default_model": ch.default_model,
            "timeout": ch.timeout,
            "enabled": ch.enabled,
            "created_at": ch.created_at,
            "last_test_at": ch.last_test_at,
            "last_test_ok": ch.last_test_ok,
            "consecutive_failures": ch.consecutive_failures,
            "api_key_preview": mask_key_display(ch.api_key),
        })
    return web.json_response({"channels": channels})


async def handle_channel_create(request: web.Request) -> web.Response:
    """POST /api/frontend/channels — add a new LLM channel."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    mgr = _get_channel_mgr(request)
    if not mgr:
        return web.json_response({"error": "channel manager not configured"}, status=503)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=422)

    name = body.get("name", "").strip()
    if not name:
        return web.json_response({"error": "渠道名称不能为空"}, status=400)

    ch = mgr.add_channel(
        name=name,
        base_url=body.get("base_url", ""),
        api_key=body.get("api_key", ""),
        provider=body.get("provider", "openai_compatible"),
        models=body.get("models", []),
        default_model=body.get("default_model", ""),
        timeout=body.get("timeout", 30),
    )
    return web.json_response({
        "channel": {
            "name": ch.name,
            "base_url": ch.base_url,
            "provider": ch.provider,
            "models": ch.models,
            "default_model": ch.default_model,
            "timeout": ch.timeout,
            "enabled": ch.enabled,
        }
    })


async def handle_channel_update(request: web.Request) -> web.Response:
    """PUT /api/frontend/channels/{name} — update a channel."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    mgr = _get_channel_mgr(request)
    if not mgr:
        return web.json_response({"error": "channel manager not configured"}, status=503)

    name = request.match_info["name"]
    ch = mgr.get_channel(name)
    if not ch:
        return web.json_response({"error": "渠道不存在"}, status=404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=422)

    if "base_url" in body:
        ch.base_url = body["base_url"]
    if "api_key" in body and body["api_key"]:
        ch.api_key = body["api_key"]
    if "provider" in body:
        ch.provider = body["provider"]
    if "default_model" in body:
        ch.default_model = body["default_model"]
    if "timeout" in body:
        ch.timeout = int(body["timeout"])
    if "enabled" in body:
        ch.enabled = bool(body["enabled"])
    if "models" in body:
        ch.models = body["models"]

    mgr._save_to_file()
    return web.json_response({"success": True})


async def handle_channel_delete(request: web.Request) -> web.Response:
    """DELETE /api/frontend/channels/{name} — remove a channel."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    mgr = _get_channel_mgr(request)
    if not mgr:
        return web.json_response({"error": "channel manager not configured"}, status=503)

    name = request.match_info["name"]
    if mgr.remove_channel(name):
        return web.json_response({"success": True})
    return web.json_response({"error": "渠道不存在"}, status=404)


async def handle_channel_test(request: web.Request) -> web.Response:
    """POST /api/frontend/channels/{name}/test — test channel connectivity."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    mgr = _get_channel_mgr(request)
    if not mgr:
        return web.json_response({"error": "channel manager not configured"}, status=503)

    name = request.match_info["name"]
    result = await mgr.test_channel(name)
    return web.json_response({
        "ok": result.ok,
        "channel_name": result.channel_name,
        "latency_ms": round(result.latency_ms, 1),
        "error": result.error,
        "status_code": result.status_code,
    })


async def handle_channel_fetch_models(request: web.Request) -> web.Response:
    """POST /api/frontend/channels/{name}/fetch-models — fetch available models."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    mgr = _get_channel_mgr(request)
    if not mgr:
        return web.json_response({"error": "channel manager not configured"}, status=503)

    name = request.match_info["name"]
    models = await mgr.fetch_models(name)
    return web.json_response({"models": models})


async def handle_channels_health(request: web.Request) -> web.Response:
    """GET /api/frontend/channels/health — health summary for all channels."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    mgr = _get_channel_mgr(request)
    if not mgr:
        return web.json_response({"health": {}})
    return web.json_response({"health": mgr.get_health_summary()})


def register_channel_routes(app: web.Application) -> None:
    """Register LLM channel management routes."""
    app.router.add_get("/api/frontend/channels", handle_channels_list)
    app.router.add_post("/api/frontend/channels", handle_channel_create)
    app.router.add_put("/api/frontend/channels/{name}", handle_channel_update)
    app.router.add_delete("/api/frontend/channels/{name}", handle_channel_delete)
    app.router.add_post("/api/frontend/channels/{name}/test", handle_channel_test)
    app.router.add_post("/api/frontend/channels/{name}/fetch-models", handle_channel_fetch_models)
    app.router.add_get("/api/frontend/channels/health", handle_channels_health)

"""Notification API routes —— 站内拉取式通知。

recipient 强制取当前登录用户的 username，忽略任何客户端传入值。
"""

from __future__ import annotations

import logging

from aiohttp import web

from xiaopaw.frontend.routes.helpers import check_auth, get_current_user

logger = logging.getLogger(__name__)


def _error(msg: str, status: int = 400) -> web.Response:
    return web.json_response({"error": msg}, status=status)


def _serialize(row: dict) -> dict:
    """把通知行中的 datetime 转为 isoformat 供 JSON 序列化。"""
    out = dict(row)
    created = out.get("created_at")
    if created is not None and hasattr(created, "isoformat"):
        out["created_at"] = created.isoformat()
    return out


def _resolve(request: web.Request):
    """返回 (store, username) 或错误响应。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    user = get_current_user(request)
    if not user:
        return _error("unauthorized", 401)
    store = request.app.get("notification_store")
    if not store:
        return _error("notification service not available", 503)
    return store, user["username"]


async def handle_list(request: web.Request) -> web.Response:
    """GET /api/frontend/notifications — 分页列表。"""
    resolved = _resolve(request)
    if isinstance(resolved, web.Response):
        return resolved
    store, username = resolved

    unread_only = request.query.get("unread_only", "").lower() in ("1", "true", "yes")
    try:
        page = max(1, int(request.query.get("page", "1")))
        page_size = min(100, max(1, int(request.query.get("page_size", "20"))))
    except ValueError:
        return _error("invalid pagination", 422)

    result = store.list(username, unread_only=unread_only, page=page, page_size=page_size)
    return web.json_response({
        "notifications": [_serialize(r) for r in result.get("notifications", [])],
        "total": result.get("total", 0),
    })


async def handle_unread_count(request: web.Request) -> web.Response:
    """GET /api/frontend/notifications/unread-count — 未读数。"""
    resolved = _resolve(request)
    if isinstance(resolved, web.Response):
        return resolved
    store, username = resolved
    return web.json_response({"count": store.unread_count(username)})


async def handle_mark_read(request: web.Request) -> web.Response:
    """POST /api/frontend/notifications/{id}/read — 标记单条已读。"""
    resolved = _resolve(request)
    if isinstance(resolved, web.Response):
        return resolved
    store, username = resolved
    try:
        notif_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return _error("invalid notification id", 422)
    if not store.mark_read(notif_id, username):
        return _error("not found", 404)
    return web.json_response({"ok": True})


async def handle_mark_all_read(request: web.Request) -> web.Response:
    """POST /api/frontend/notifications/read-all — 全部已读。"""
    resolved = _resolve(request)
    if isinstance(resolved, web.Response):
        return resolved
    store, username = resolved
    return web.json_response({"updated": store.mark_all_read(username)})


def register_notification_routes(app: web.Application) -> None:
    """注册通知路由。"""
    app.router.add_get("/api/frontend/notifications", handle_list)
    app.router.add_get(
        "/api/frontend/notifications/unread-count", handle_unread_count
    )
    app.router.add_post(
        "/api/frontend/notifications/{id}/read", handle_mark_read
    )
    app.router.add_post(
        "/api/frontend/notifications/read-all", handle_mark_all_read
    )

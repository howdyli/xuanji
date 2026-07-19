"""Auth route handlers: register, login, logout, me, profile, password."""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from xiaopaw.frontend.routes.helpers import get_current_user

logger = logging.getLogger(__name__)


async def handle_auth_register(request: web.Request) -> web.Response:
    """POST /api/frontend/auth/register — create a new user account."""
    try:
        body = await request.json()
        username = body.get("username", "").strip()
        password = body.get("password", "")
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=422)

    user_auth = request.app.get("user_auth")
    if not user_auth:
        return web.json_response({"error": "auth not configured"}, status=503)

    try:
        token, user = user_auth.register(username, password)
        return web.json_response({"token": token, "user": user})
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def handle_auth_login(request: web.Request) -> web.Response:
    """POST /api/frontend/auth/login — login with username and password."""
    try:
        body = await request.json()
        username = body.get("username", "").strip()
        password = body.get("password", "")
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=422)

    user_auth = request.app.get("user_auth")
    if not user_auth:
        return web.json_response({"error": "auth not configured"}, status=503)

    try:
        # Offload CPU-intensive PBKDF2 password hashing to thread pool
        token, user = await asyncio.to_thread(user_auth.login, username, password)
        return web.json_response({"token": token, "user": user})
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=401)


async def handle_auth_logout(request: web.Request) -> web.Response:
    """POST /api/frontend/auth/logout — destroy the current session."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        user_auth = request.app.get("user_auth")
        if user_auth:
            user_auth.logout(auth[7:])
    return web.json_response({"success": True})


async def handle_auth_me(request: web.Request) -> web.Response:
    """GET /api/frontend/auth/me — get current user info."""
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response({"user": user})


async def handle_auth_update_profile(request: web.Request) -> web.Response:
    """PUT /api/frontend/auth/profile — update current user's profile."""
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=422)

    user_auth = request.app.get("user_auth")
    if not user_auth:
        return web.json_response({"error": "auth not configured"}, status=503)

    new_username = body.get("username", "").strip()
    if not new_username:
        return web.json_response({"error": "用户名不能为空"}, status=400)

    try:
        updated = user_auth.update_username(user["id"], new_username)
        return web.json_response({"user": updated})
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def handle_auth_change_password(request: web.Request) -> web.Response:
    """POST /api/frontend/auth/change-password — change current user's password."""
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=422)

    user_auth = request.app.get("user_auth")
    if not user_auth:
        return web.json_response({"error": "auth not configured"}, status=503)

    old_password = body.get("old_password", "")
    new_password = body.get("new_password", "")

    if not old_password or not new_password:
        return web.json_response({"error": "请填写完整"}, status=400)

    try:
        user_auth.change_password(user["id"], old_password, new_password)
        return web.json_response({"success": True})
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)


def register_auth_routes(app: web.Application) -> None:
    """Register auth routes."""
    app.router.add_post("/api/frontend/auth/register", handle_auth_register)
    app.router.add_post("/api/frontend/auth/login", handle_auth_login)
    app.router.add_post("/api/frontend/auth/logout", handle_auth_logout)
    app.router.add_get("/api/frontend/auth/me", handle_auth_me)
    app.router.add_put("/api/frontend/auth/profile", handle_auth_update_profile)
    app.router.add_post("/api/frontend/auth/change-password", handle_auth_change_password)

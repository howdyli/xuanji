"""Team collaboration API routes.

Endpoints for team CRUD, member management, invitations,
and session sharing within teams.
"""

from __future__ import annotations

import logging

from aiohttp import web

from xiaopaw.frontend.routes.helpers import check_auth, get_current_user
from xiaopaw.frontend.team import TeamStore

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────


def _get_team_store(request: web.Request) -> TeamStore | None:
    return request.app.get("team_store")


def _get_user_id(request: web.Request) -> int | None:
    user = get_current_user(request)
    return user["id"] if user else None


def _error(msg: str, status: int = 400) -> web.Response:
    return web.json_response({"error": msg}, status=status)


# ── Team CRUD ──────────────────────────────────────────────────────────────


async def handle_team_create(request: web.Request) -> web.Response:
    """POST /api/frontend/teams — 创建团队。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user_id = _get_user_id(request)
    if not user_id:
        return _error("unauthorized", 401)

    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON body", 422)

    name = body.get("name", "").strip()
    description = body.get("description", "").strip()

    try:
        team = store.create_team(name, description, user_id)
    except ValueError as e:
        return _error(str(e))

    return web.json_response({"team": team}, status=201)


async def handle_team_list(request: web.Request) -> web.Response:
    """GET /api/frontend/teams — 列出我加入的所有团队。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user_id = _get_user_id(request)
    if not user_id:
        return _error("unauthorized", 401)

    teams = store.list_teams_for_user(user_id)
    return web.json_response({"teams": teams})


async def handle_team_detail(request: web.Request) -> web.Response:
    """GET /api/frontend/teams/{id} — 团队详情 + 成员列表。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user_id = _get_user_id(request)
    if not user_id:
        return _error("unauthorized", 401)

    team_id = int(request.match_info["id"])
    if not store.is_member(team_id, user_id):
        return _error("not a team member", 403)

    team = store.get_team(team_id)
    if not team:
        return _error("team not found", 404)

    members = store.list_members(team_id)
    team["members"] = members
    return web.json_response({"team": team})


async def handle_team_delete(request: web.Request) -> web.Response:
    """DELETE /api/frontend/teams/{id} — 解散团队（仅 owner）。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user_id = _get_user_id(request)
    if not user_id:
        return _error("unauthorized", 401)

    team_id = int(request.match_info["id"])
    try:
        ok = store.delete_team(team_id, user_id)
    except ValueError as e:
        return _error(str(e), 403)

    if not ok:
        return _error("team not found", 404)
    return web.json_response({"success": True})


# ── Member Management ──────────────────────────────────────────────────────


async def handle_team_members(request: web.Request) -> web.Response:
    """GET /api/frontend/teams/{id}/members — 成员列表。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user_id = _get_user_id(request)
    if not user_id:
        return _error("unauthorized", 401)

    team_id = int(request.match_info["id"])
    if not store.is_member(team_id, user_id):
        return _error("not a team member", 403)

    members = store.list_members(team_id)
    return web.json_response({"members": members})


async def handle_team_member_remove(request: web.Request) -> web.Response:
    """DELETE /api/frontend/teams/{id}/members/{uid} — 移除成员（admin+）。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user_id = _get_user_id(request)
    if not user_id:
        return _error("unauthorized", 401)

    team_id = int(request.match_info["id"])
    target_uid = int(request.match_info["uid"])

    requester_role = store.get_member_role(team_id, user_id)
    if requester_role not in ("owner", "admin"):
        return _error("权限不足", 403)

    try:
        ok = store.remove_member(team_id, target_uid)
    except ValueError as e:
        return _error(str(e), 403)

    if not ok:
        return _error("member not found", 404)
    return web.json_response({"success": True})


async def handle_team_member_role(request: web.Request) -> web.Response:
    """PUT /api/frontend/teams/{id}/members/{uid}/role — 变更角色（owner only）。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user_id = _get_user_id(request)
    if not user_id:
        return _error("unauthorized", 401)

    team_id = int(request.match_info["id"])
    target_uid = int(request.match_info["uid"])

    requester_role = store.get_member_role(team_id, user_id)
    if requester_role != "owner":
        return _error("只有创建者可以变更角色", 403)

    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON body", 422)

    new_role = body.get("role", "").strip()
    try:
        ok = store.update_member_role(team_id, target_uid, new_role)
    except ValueError as e:
        return _error(str(e))

    if not ok:
        return _error("member not found", 404)
    return web.json_response({"success": True})


# ── Invitations ────────────────────────────────────────────────────────────


async def handle_invitation_create(request: web.Request) -> web.Response:
    """POST /api/frontend/teams/{id}/invitations — 生成邀请码。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user_id = _get_user_id(request)
    if not user_id:
        return _error("unauthorized", 401)

    team_id = int(request.match_info["id"])
    try:
        invitation = store.create_invitation(team_id, user_id)
    except ValueError as e:
        return _error(str(e), 403)

    return web.json_response({"invitation": invitation}, status=201)


async def handle_invitation_list(request: web.Request) -> web.Response:
    """GET /api/frontend/teams/{id}/invitations — 待处理邀请列表。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user_id = _get_user_id(request)
    if not user_id:
        return _error("unauthorized", 401)

    team_id = int(request.match_info["id"])
    role = store.get_member_role(team_id, user_id)
    if role not in ("owner", "admin"):
        return _error("权限不足", 403)

    invitations = store.list_pending_invitations(team_id)
    return web.json_response({"invitations": invitations})


async def handle_team_join(request: web.Request) -> web.Response:
    """POST /api/frontend/teams/join — 通过邀请码加入团队。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user_id = _get_user_id(request)
    if not user_id:
        return _error("unauthorized", 401)

    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON body", 422)

    code = body.get("code", "").strip()
    if not code:
        return _error("邀请码不能为空", 422)

    try:
        team = store.accept_invitation(code, user_id)
    except ValueError as e:
        return _error(str(e))

    return web.json_response({"team": team})


# ── Team Sessions (shared) ─────────────────────────────────────────────────


async def handle_team_sessions(request: web.Request) -> web.Response:
    """GET /api/frontend/teams/{id}/sessions — 列出团队共享会话。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user_id = _get_user_id(request)
    if not user_id:
        return _error("unauthorized", 401)

    team_id = int(request.match_info["id"])
    if not store.is_member(team_id, user_id):
        return _error("not a team member", 403)

    pg_store = request.app.get("pg_store")
    if not pg_store or not pg_store._available:
        return web.json_response({"sessions": []})

    try:
        import psycopg2
        import psycopg2.extras
        with psycopg2.connect(pg_store._dsn) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, routing_key, title, message_count, team_id,
                              shared_by, share_permission, created_at, updated_at
                       FROM sessions WHERE team_id = %s
                       ORDER BY updated_at DESC LIMIT 50""",
                    (team_id,),
                )
                sessions = list(cur.fetchall())
                for s in sessions:
                    for k in ("created_at", "updated_at"):
                        if s.get(k):
                            s[k] = s[k].isoformat()
    except Exception as exc:
        logger.warning("team_sessions query failed: %s", exc)
        sessions = []

    return web.json_response({"sessions": sessions})


# ── Session Sharing ────────────────────────────────────────────────────────


async def handle_session_share(request: web.Request) -> web.Response:
    """POST /api/frontend/sessions/{session_id}/share — 共享会话到团队。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    store = _get_team_store(request)
    if not store:
        return _error("team service not available", 503)
    user = get_current_user(request)
    if not user:
        return _error("unauthorized", 401)

    session_id = request.match_info["session_id"]

    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON body", 422)

    team_id = body.get("team_id")
    permission = body.get("permission", "view")
    if not team_id:
        return _error("team_id is required", 422)
    if permission not in ("view", "edit"):
        return _error("permission must be 'view' or 'edit'", 422)

    # 验证用户是团队成员
    if not store.is_member(int(team_id), user["id"]):
        return _error("not a team member", 403)

    pg_store = request.app.get("pg_store")
    if not pg_store or not pg_store._available:
        return _error("database not available", 503)

    try:
        import psycopg2
        with psycopg2.connect(pg_store._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE sessions
                       SET team_id = %s, shared_by = %s, share_permission = %s
                       WHERE id = %s""",
                    (team_id, user["username"], permission, session_id),
                )
                if cur.rowcount == 0:
                    return _error("session not found", 404)
            conn.commit()
    except Exception as exc:
        logger.warning("session share failed: %s", exc)
        return _error("share failed", 500)

    return web.json_response({"success": True, "session_id": session_id, "team_id": team_id})


async def handle_session_unshare(request: web.Request) -> web.Response:
    """DELETE /api/frontend/sessions/{session_id}/share — 取消共享。"""
    if not check_auth(request):
        return _error("unauthorized", 401)
    user = get_current_user(request)
    if not user:
        return _error("unauthorized", 401)

    session_id = request.match_info["session_id"]

    pg_store = request.app.get("pg_store")
    if not pg_store or not pg_store._available:
        return _error("database not available", 503)

    try:
        import psycopg2
        with psycopg2.connect(pg_store._dsn) as conn:
            with conn.cursor() as cur:
                # 只有共享者本人或团队 admin+ 可以取消
                cur.execute(
                    """UPDATE sessions
                       SET team_id = NULL, shared_by = '', share_permission = 'view'
                       WHERE id = %s AND shared_by = %s""",
                    (session_id, user["username"]),
                )
                if cur.rowcount == 0:
                    # 尝试 admin 权限取消
                    cur.execute(
                        "SELECT team_id FROM sessions WHERE id = %s", (session_id,)
                    )
                    row = cur.fetchone()
                    if not row or not row[0]:
                        return _error("session not shared or not found", 404)
                    store = _get_team_store(request)
                    role = store.get_member_role(row[0], user["id"]) if store else None
                    if role not in ("owner", "admin"):
                        return _error("权限不足", 403)
                    cur.execute(
                        """UPDATE sessions
                           SET team_id = NULL, shared_by = '', share_permission = 'view'
                           WHERE id = %s""",
                        (session_id,),
                    )
            conn.commit()
    except Exception as exc:
        logger.warning("session unshare failed: %s", exc)
        return _error("unshare failed", 500)

    return web.json_response({"success": True})


# ── Route Registration ─────────────────────────────────────────────────────


def register_team_routes(app: web.Application) -> None:
    """Register team collaboration routes."""
    # Team CRUD
    app.router.add_post("/api/frontend/teams", handle_team_create)
    app.router.add_get("/api/frontend/teams", handle_team_list)
    app.router.add_get("/api/frontend/teams/{id}", handle_team_detail)
    app.router.add_delete("/api/frontend/teams/{id}", handle_team_delete)

    # Members
    app.router.add_get("/api/frontend/teams/{id}/members", handle_team_members)
    app.router.add_delete("/api/frontend/teams/{id}/members/{uid}", handle_team_member_remove)
    app.router.add_put("/api/frontend/teams/{id}/members/{uid}/role", handle_team_member_role)

    # Invitations
    app.router.add_post("/api/frontend/teams/{id}/invitations", handle_invitation_create)
    app.router.add_get("/api/frontend/teams/{id}/invitations", handle_invitation_list)
    app.router.add_post("/api/frontend/teams/join", handle_team_join)

    # Team sessions
    app.router.add_get("/api/frontend/teams/{id}/sessions", handle_team_sessions)

    # Session sharing
    app.router.add_post("/api/frontend/sessions/{session_id}/share", handle_session_share)
    app.router.add_delete("/api/frontend/sessions/{session_id}/share", handle_session_unshare)

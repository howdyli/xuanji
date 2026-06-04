"""REST API endpoints for skills management."""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

from xiaopaw.skills_mgmt.packager import (
    DEFAULT_MAX_ARCHIVE_BYTES,
    pack_skill,
    unpack_skill,
)
from xiaopaw.skills_mgmt.market import MarketError, MarketRegistry
from xiaopaw.skills_mgmt.registry import SkillRegistry
from xiaopaw.skills_mgmt.validator import ValidationError

logger = logging.getLogger(__name__)


def _check_auth(request: web.Request) -> bool:
    """Check Bearer token — session token (UserAuth) or static fallback."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        token = request.app.get("frontend_token", "")
        user_auth = request.app.get("user_auth")
        return not token and not user_auth
    bearer = auth[7:]
    # 1) Session token via UserAuth
    user_auth = request.app.get("user_auth")
    if user_auth and user_auth.validate_token(bearer) is not None:
        return True
    # 2) Fallback: static token for dev backward compat
    static_token = request.app.get("frontend_token", "")
    if static_token and bearer == static_token:
        return True
    return False


def _get_registry(request: web.Request) -> SkillRegistry | None:
    return request.app.get("skill_registry")


def _get_market(request: web.Request) -> MarketRegistry | None:
    return request.app.get("market_registry")


def _get_market_sync(request: web.Request):
    return request.app.get("market_sync")


def _err(code: str, msg: str = "", status: int = 400) -> web.Response:
    return web.json_response({"error": code, "message": msg or code}, status=status)


# ─── List / Detail ────────────────────────────────────────────


async def handle_list_skills(request: web.Request) -> web.Response:
    """GET /api/frontend/skills - list all skills."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    reg = _get_registry(request)
    if not reg:
        return _err("registry_unavailable", status=503)
    skills = [s.to_dict() for s in reg.list_all()]
    return web.json_response({"skills": skills, "total": len(skills)})


async def handle_get_skill(request: web.Request) -> web.Response:
    """GET /api/frontend/skills/{name} - skill detail with SKILL.md content."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    reg = _get_registry(request)
    if not reg:
        return _err("registry_unavailable", status=503)
    name = request.match_info.get("name", "")
    info = reg.get(name)
    if not info or not info.path:
        return _err("not_found", status=404)
    skill_md_text = ""
    skill_md = info.path / "SKILL.md"
    if skill_md.exists():
        try:
            skill_md_text = skill_md.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("read SKILL.md failed: %s", exc)
    return web.json_response({
        **info.to_dict(),
        "skill_md": skill_md_text,
    })


# ─── Create / Update / Delete ─────────────────────────────────


async def handle_create_skill(request: web.Request) -> web.Response:
    """POST /api/frontend/skills - create a new user skill via JSON.

    Body:
    {
      "name": "my-skill", "description": "...",
      "body": "<markdown body>",
      "type": "task" | "reference",
      "author": "alice", "version": "1.0.0",
      "scripts": { "run.py": "<content>", ... },
      "overwrite": false
    }
    """
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    reg = _get_registry(request)
    if not reg:
        return _err("registry_unavailable", status=503)
    try:
        body = await request.json()
    except Exception as exc:
        return _err("bad_request", str(exc), status=422)

    name = str(body.get("name", "")).strip()
    description = str(body.get("description", "")).strip()
    md_body = str(body.get("body", "")).strip()
    type_ = str(body.get("type", "task")).strip() or "task"
    if type_ not in ("task", "reference"):
        return _err("invalid_type", status=422)
    if not name or not description or not md_body:
        return _err("missing_fields", "name/description/body required", status=422)
    scripts = body.get("scripts") or {}
    if not isinstance(scripts, dict):
        return _err("invalid_scripts", status=422)

    ok, code = reg.write_user_skill(
        name=name,
        description=description,
        body=md_body,
        type_=type_,
        author=str(body.get("author", "")),
        version=str(body.get("version", "1.0.0")),
        scripts={str(k): str(v) for k, v in scripts.items()},
        overwrite=bool(body.get("overwrite", False)),
    )
    if not ok:
        status = 409 if code in ("exists", "builtin_conflict") else 422
        return _err(code, status=status)
    return web.json_response({"ok": True, "name": name})


async def handle_delete_skill(request: web.Request) -> web.Response:
    """DELETE /api/frontend/skills/{name} - delete a user skill."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    reg = _get_registry(request)
    if not reg:
        return _err("registry_unavailable", status=503)
    name = request.match_info.get("name", "")
    ok, code = reg.delete_user_skill(name)
    if not ok:
        status = 403 if code == "builtin_protected" else 404 if code == "not_found" else 500
        return _err(code, status=status)
    return web.json_response({"ok": True})


async def handle_toggle_skill(request: web.Request) -> web.Response:
    """POST /api/frontend/skills/{name}/toggle - enable/disable a skill."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    reg = _get_registry(request)
    if not reg:
        return _err("registry_unavailable", status=503)
    name = request.match_info.get("name", "")
    info = reg.get(name)
    if not info:
        return _err("not_found", status=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    enabled = bool(body.get("enabled", not info.enabled))
    ok = reg.set_enabled(name, enabled)
    if not ok:
        return _err("update_failed", status=500)
    return web.json_response({"ok": True, "name": name, "enabled": enabled})


# ─── Upload / Download ────────────────────────────────────────


async def handle_upload_skill(request: web.Request) -> web.Response:
    """POST /api/frontend/skills/upload - upload a .zip package (multipart)."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    reg = _get_registry(request)
    if not reg:
        return _err("registry_unavailable", status=503)

    max_bytes = request.app.get("skills_max_upload_bytes", DEFAULT_MAX_ARCHIVE_BYTES)
    overwrite = request.query.get("overwrite", "").lower() in ("1", "true", "yes")

    # Accept either multipart/form-data OR raw application/zip body
    archive_bytes = b""
    ctype = (request.content_type or "").lower()
    if "multipart" in ctype:
        reader = await request.multipart()
        async for part in reader:
            if part.name in ("file", "archive", "skill"):
                buf = bytearray()
                while True:
                    chunk = await part.read_chunk(64 * 1024)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        return _err("too_large", status=413)
                archive_bytes = bytes(buf)
                break
    else:
        archive_bytes = await request.read()

    if not archive_bytes:
        return _err("empty_body", status=422)
    if len(archive_bytes) > max_bytes:
        return _err("too_large", status=413)

    try:
        name, _target = unpack_skill(
            archive_bytes,
            target_root=reg.user_dir,
            max_archive_bytes=max_bytes,
            overwrite=overwrite,
        )
    except ValidationError as exc:
        status = 409 if exc.code == "exists" else 413 if "large" in exc.code else 422
        return _err(exc.code, exc.message, status=status)
    except Exception as exc:
        logger.warning("upload_skill failed: %s", exc)
        return _err("upload_failed", str(exc), status=500)

    # Sync new skill into DB
    reg.sync_to_db()
    return web.json_response({"ok": True, "name": name})


async def handle_download_skill(request: web.Request) -> web.Response:
    """GET /api/frontend/skills/{name}/download - return .zip blob."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    reg = _get_registry(request)
    if not reg:
        return _err("registry_unavailable", status=503)
    name = request.match_info.get("name", "")
    info = reg.get(name)
    if not info or not info.path:
        return _err("not_found", status=404)
    try:
        data = pack_skill(info.path)
    except Exception as exc:
        logger.warning("pack_skill failed: %s", exc)
        return _err("pack_failed", status=500)
    return web.Response(
        body=data,
        content_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


# ─── Session-skill bindings ───────────────────────────────────


async def handle_get_session_skills(request: web.Request) -> web.Response:
    """GET /api/frontend/sessions/{sid}/skills - skills enabled for a session."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    reg = _get_registry(request)
    if not reg:
        return _err("registry_unavailable", status=503)
    sid = request.match_info.get("sid", "")
    names = reg.get_session_skills(sid)
    return web.json_response({
        "session_id": sid,
        "skills": sorted(names) if names is not None else None,
    })


async def handle_set_session_skills(request: web.Request) -> web.Response:
    """PUT /api/frontend/sessions/{sid}/skills - set the skill subset for a session.

    Body: { "skills": ["baidu_search", "pdf"] }  // empty list = use all globally enabled
    """
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    reg = _get_registry(request)
    if not reg:
        return _err("registry_unavailable", status=503)
    sid = request.match_info.get("sid", "")
    try:
        body = await request.json()
    except Exception as exc:
        return _err("bad_request", str(exc), status=422)
    skills = body.get("skills") or []
    if not isinstance(skills, list):
        return _err("invalid_skills", status=422)
    skills = [str(s) for s in skills]
    ok = reg.set_session_skills(sid, skills)
    if not ok:
        return _err("update_failed", status=500)
    return web.json_response({"ok": True, "session_id": sid, "skills": skills})


# ─── Routes registration ──────────────────────────────────────


async def handle_list_market(request: web.Request) -> web.Response:
    """GET /api/frontend/market/skills - cached remote-repo index.

    Query params: ?search=<text>&source=vercel|clawhub
    Each entry includes ``installed: bool`` so the frontend can switch the
    button label without a second round-trip.
    """
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    market = _get_market(request)
    if not market:
        return _err("market_unavailable", status=503)
    search = request.query.get("search") or None
    source = request.query.get("source") or None
    entries = market.list_market(search=search, source_type=source)
    installed = market.installed_names()
    items = [e.to_dict(installed=e.name in installed) for e in entries]
    return web.json_response({"skills": items, "total": len(items)})


async def handle_get_market_entry(request: web.Request) -> web.Response:
    """GET /api/frontend/market/skills/{name} - single market entry detail."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    market = _get_market(request)
    if not market:
        return _err("market_unavailable", status=503)
    name = request.match_info.get("name", "")
    entry = market.get_market(name)
    if not entry:
        return _err("not_found", status=404)
    installed = name in market.installed_names()
    return web.json_response(entry.to_dict(installed=installed))


async def handle_install_market(request: web.Request) -> web.Response:
    """POST /api/frontend/market/skills/{name}/install - download + unpack.

    Query: ?overwrite=true to replace an existing local skill.
    """
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    market = _get_market(request)
    if not market:
        return _err("market_unavailable", status=503)
    name = request.match_info.get("name", "")
    overwrite = request.query.get("overwrite", "").lower() in ("1", "true", "yes")
    try:
        installed_name = await market.install(name, overwrite=overwrite)
    except MarketError as exc:
        status = (
            404 if exc.code == "not_found"
            else 409 if exc.code in ("exists", "name_mismatch")
            else 413 if "large" in exc.code
            else 502 if exc.code == "download_failed"
            else 422
        )
        return _err(exc.code, exc.message, status=status)
    except Exception as exc:
        logger.warning("install_market failed: %s", exc)
        return _err("install_failed", str(exc), status=500)
    return web.json_response({"ok": True, "name": installed_name})


async def handle_refresh_market(request: web.Request) -> web.Response:
    """POST /api/frontend/market/refresh - trigger one immediate sync cycle.

    Returns the per-source summary; does not block routine background sync.
    """
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    sync = _get_market_sync(request)
    if not sync:
        return _err("market_sync_unavailable", status=503)
    try:
        summary = await sync.sync_to_db()
    except Exception as exc:
        logger.warning("refresh_market failed: %s", exc)
        return _err("refresh_failed", str(exc), status=500)
    return web.json_response({"ok": True, **summary})


def register_routes(app: web.Application) -> None:
    """Register skills management routes onto the given aiohttp app."""
    app.router.add_get("/api/frontend/skills", handle_list_skills)
    app.router.add_post("/api/frontend/skills", handle_create_skill)
    app.router.add_post("/api/frontend/skills/upload", handle_upload_skill)
    app.router.add_get("/api/frontend/skills/{name}", handle_get_skill)
    app.router.add_delete("/api/frontend/skills/{name}", handle_delete_skill)
    app.router.add_post("/api/frontend/skills/{name}/toggle", handle_toggle_skill)
    app.router.add_get("/api/frontend/skills/{name}/download", handle_download_skill)
    app.router.add_get("/api/frontend/sessions/{sid}/skills", handle_get_session_skills)
    app.router.add_put("/api/frontend/sessions/{sid}/skills", handle_set_session_skills)
    # Market routes (cached remote-repo index + one-click install)
    app.router.add_get("/api/frontend/market/skills", handle_list_market)
    app.router.add_get("/api/frontend/market/skills/{name}", handle_get_market_entry)
    app.router.add_post("/api/frontend/market/skills/{name}/install", handle_install_market)
    app.router.add_post("/api/frontend/market/refresh", handle_refresh_market)

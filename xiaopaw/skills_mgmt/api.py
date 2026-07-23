"""REST API endpoints for skills management."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from aiohttp import web

from xiaopaw.skills_mgmt.community import CommunityError, CommunityRegistry
from xiaopaw.skills_mgmt.packager import (
    DEFAULT_MAX_ARCHIVE_BYTES,
    pack_skill,
    unpack_skill,
)
from xiaopaw.skills_mgmt.market import MarketError, MarketRegistry
from xiaopaw.skills_mgmt.registry import SkillRegistry
from xiaopaw.skills_mgmt.validator import ValidationError
from xiaopaw.skills_mgmt.community import CommunityError, CommunityRegistry

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


def _get_community(request: web.Request) -> CommunityRegistry | None:
    return request.app.get("community_registry")


def _get_community(request: web.Request) -> CommunityRegistry | None:
    return request.app.get("community_registry")


def _get_current_user(request: web.Request) -> dict | None:
    """Extract authenticated user dict ({id, username}) from Bearer token.

    Returns None if auth fails or user_auth is unavailable.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    bearer = auth[7:]
    user_auth = request.app.get("user_auth")
    if user_auth:
        return user_auth.get_user_by_token(bearer)
    # Fallback: static token — no real user identity
    static_token = request.app.get("frontend_token", "")
    if static_token and bearer == static_token:
        return {"id": 0, "username": "admin"}
    return None


def _err(code: str, msg: str = "", status: int = 400) -> web.Response:
    return web.json_response({"error": code, "message": msg or code}, status=status)


def _require_admin(request: web.Request) -> dict | None:
    """Return the current user dict if they are a platform admin, else None."""
    user = _get_current_user(request)
    if not user:
        return None
    user_auth = request.app.get("user_auth")
    if not user_auth:
        return None
    if not user_auth.is_admin(user["id"]):
        return None
    return user


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


# ─── Community API ──────────────────────────────────────────────


async def handle_list_community_skills(request: web.Request) -> web.Response:
    """GET /api/frontend/community/skills - list community skills."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    result = cr.list_skills(
        search=request.query.get("search") or None,
        category=request.query.get("category") or None,
        sort=request.query.get("sort", "popular"),
        page=int(request.query.get("page", "1")),
        page_size=int(request.query.get("page_size", "20")),
    )
    return web.json_response(result)


async def handle_get_community_skill(request: web.Request) -> web.Response:
    """GET /api/frontend/community/skills/{name} - community skill detail."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    skill = cr.get_skill(name)
    if not skill:
        return _err("not_found", status=404)
    return web.json_response(skill)


async def handle_install_community_skill(request: web.Request) -> web.Response:
    """POST /api/frontend/community/skills/{name}/install - install community skill."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    try:
        body = await request.json() if request.can_read_body else {}
    except Exception:
        body = {}
    user_id = body.get("user_id", "anonymous")
    try:
        installed_name = await cr.install_skill(name, user_id=user_id)
    except CommunityError as exc:
        status = 404 if exc.code == "not_found" else 502 if exc.code == "download_failed" else 422
        return _err(exc.code, exc.message, status=status)
    except Exception as exc:
        logger.warning("install_community_skill failed: %s", exc)
        return _err("install_failed", str(exc), status=500)
    return web.json_response({"ok": True, "name": installed_name})


async def handle_publish_community_skill(request: web.Request) -> web.Response:
    """POST /api/frontend/community/skills/publish - publish skill to community."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    reader = await request.multipart()
    metadata: dict = {}
    zip_path: Path | None = None
    async for part in reader:
        if part.name == "metadata":
            import json as _json
            raw = await part.text()
            metadata = _json.loads(raw)
        elif part.name in ("file", "archive", "zip"):
            import tempfile
            buf = bytearray()
            while True:
                chunk = await part.read_chunk(64 * 1024)
                if not chunk:
                    break
                buf.extend(chunk)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
            tmp.write(bytes(buf))
            tmp.close()
            zip_path = Path(tmp.name)
    if not zip_path:
        return _err("missing_file", "no archive uploaded", status=422)
    try:
        row = cr.publish_skill(
            publisher=metadata.get("publisher", "anonymous"),
            metadata=metadata,
            zip_path=zip_path,
        )
    except CommunityError as exc:
        status = 409 if exc.code == "duplicate_name" else 422
        return _err(exc.code, exc.message, status=status)
    except Exception as exc:
        logger.warning("publish_community_skill failed: %s", exc)
        return _err("publish_failed", str(exc), status=500)
    finally:
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass
    return web.json_response({"ok": True, "skill": row})


async def handle_update_community_skill(request: web.Request) -> web.Response:
    """PUT /api/frontend/community/skills/{name} - update community skill."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    try:
        body = await request.json()
    except Exception:
        return _err("bad_request", status=422)
    publisher = body.get("publisher", "anonymous")
    updates = {k: v for k, v in body.items() if k != "publisher"}
    try:
        row = cr.update_skill(name, publisher=publisher, updates=updates)
    except CommunityError as exc:
        status = 404 if exc.code in ("not_found", "not_owner") else 422
        return _err(exc.code, exc.message, status=status)
    except Exception as exc:
        logger.warning("update_community_skill failed: %s", exc)
        return _err("update_failed", str(exc), status=500)
    if not row:
        return _err("not_found", status=404)
    return web.json_response({"ok": True, "skill": row})


async def handle_withdraw_community_skill(request: web.Request) -> web.Response:
    """POST /api/frontend/community/skills/{name}/withdraw - withdraw skill."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    try:
        body = await request.json() if request.can_read_body else {}
    except Exception:
        body = {}
    publisher = body.get("publisher", "anonymous")
    ok = cr.withdraw_skill(name, publisher=publisher)
    if not ok:
        return _err("withdraw_failed", status=400)
    return web.json_response({"ok": True})


async def handle_list_community_reviews(request: web.Request) -> web.Response:
    """GET /api/frontend/community/skills/{name}/reviews - list reviews."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    result = cr.list_reviews(
        name,
        page=int(request.query.get("page", "1")),
        page_size=int(request.query.get("page_size", "10")),
    )
    return web.json_response(result)


async def handle_add_community_review(request: web.Request) -> web.Response:
    """POST /api/frontend/community/skills/{name}/reviews - add review."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    try:
        body = await request.json()
    except Exception:
        return _err("bad_request", status=422)
    user_id = body.get("user_id", "anonymous")
    rating = body.get("rating")
    if rating is None:
        return _err("missing_rating", status=422)
    try:
        review = cr.add_review(
            skill_name=name,
            user_id=user_id,
            rating=int(rating),
            comment=body.get("comment", ""),
        )
    except CommunityError as exc:
        return _err(exc.code, exc.message, status=422)
    except Exception as exc:
        logger.warning("add_community_review failed: %s", exc)
        return _err("review_failed", str(exc), status=500)
    return web.json_response({"ok": True, "review": review})


async def handle_mark_review_helpful(request: web.Request) -> web.Response:
    """POST /api/frontend/community/reviews/{id}/helpful - mark review helpful."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    review_id = int(request.match_info["id"])
    try:
        body = await request.json() if request.can_read_body else {}
    except Exception:
        body = {}
    user_id = body.get("user_id", "anonymous")
    ok = cr.mark_helpful(review_id, user_id=user_id)
    if not ok:
        return _err("not_found", status=404)
    return web.json_response({"ok": True})


async def handle_list_community_categories(request: web.Request) -> web.Response:
    """GET /api/frontend/community/categories - list skill categories."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    categories = cr.get_categories()
    return web.json_response({"categories": categories})


async def handle_get_community_rankings(request: web.Request) -> web.Response:
    """GET /api/frontend/community/rankings - skill rankings."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    period = request.query.get("period", "week")
    rankings = cr.get_rankings(period=period)
    return web.json_response({"rankings": rankings})


async def handle_get_community_featured(request: web.Request) -> web.Response:
    """GET /api/frontend/community/featured - featured skills."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    featured = cr.get_featured()
    return web.json_response({"featured": featured})


async def handle_add_community_favorite(request: web.Request) -> web.Response:
    """POST /api/frontend/community/favorites - add favorite."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    try:
        body = await request.json()
    except Exception:
        return _err("bad_request", status=422)
    user_id = body.get("user_id", "anonymous")
    skill_name = body.get("skill_name", "")
    if not skill_name:
        return _err("missing_skill_name", status=422)
    ok = cr.add_favorite(user_id=user_id, skill_name=skill_name)
    return web.json_response({"ok": ok})


async def handle_remove_community_favorite(request: web.Request) -> web.Response:
    """DELETE /api/frontend/community/favorites - remove favorite."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    try:
        body = await request.json()
    except Exception:
        return _err("bad_request", status=422)
    user_id = body.get("user_id", "anonymous")
    skill_name = body.get("skill_name", "")
    if not skill_name:
        return _err("missing_skill_name", status=422)
    ok = cr.remove_favorite(user_id=user_id, skill_name=skill_name)
    return web.json_response({"ok": ok})


async def handle_list_community_favorites(request: web.Request) -> web.Response:
    """GET /api/frontend/community/favorites/{user_id} - list user favorites."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    user_id = request.match_info["user_id"]
    favorites = cr.list_favorites(user_id=user_id)
    return web.json_response({"favorites": favorites})


async def handle_list_my_community_skills(request: web.Request) -> web.Response:
    """GET /api/frontend/community/my-skills/{publisher} - list my published skills."""
    if not _check_auth(request):
        return _err("unauthorized", status=401)
    cr = _get_community(request)
    if not cr:
        return _err("community_unavailable", status=503)
    publisher = request.match_info["publisher"]
    skills = cr.list_my_skills(publisher=publisher)
    return web.json_response({"skills": skills})


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
    # Community routes (community skill marketplace)
    app.router.add_get("/api/frontend/community/skills", handle_list_community_skills)
    app.router.add_get("/api/frontend/community/categories", handle_list_community_categories)
    app.router.add_get("/api/frontend/community/rankings", handle_get_community_rankings)
    app.router.add_get("/api/frontend/community/featured", handle_get_community_featured)
    # NOTE: /publish must be registered before /{name} to avoid path conflict
    app.router.add_post("/api/frontend/community/skills/publish", handle_publish_community_skill)
    app.router.add_get("/api/frontend/community/skills/{name}", handle_get_community_skill)
    app.router.add_post("/api/frontend/community/skills/{name}/install", handle_install_community_skill)
    app.router.add_put("/api/frontend/community/skills/{name}", handle_update_community_skill)
    app.router.add_post("/api/frontend/community/skills/{name}/withdraw", handle_withdraw_community_skill)
    app.router.add_get("/api/frontend/community/skills/{name}/reviews", handle_list_community_reviews)
    app.router.add_post("/api/frontend/community/skills/{name}/reviews", handle_add_community_review)
    app.router.add_post("/api/frontend/community/reviews/{id}/helpful", handle_mark_review_helpful)
    app.router.add_post("/api/frontend/community/favorites", handle_add_community_favorite)
    app.router.add_delete("/api/frontend/community/favorites", handle_remove_community_favorite)
    app.router.add_get("/api/frontend/community/favorites/{user_id}", handle_list_community_favorites)
    app.router.add_get("/api/frontend/community/my-skills/{publisher}", handle_list_my_community_skills)


# ─── Community Market Handlers ────────────────────────────────


async def handle_community_list_skills(request: web.Request) -> web.Response:
    """GET /api/frontend/market/community/skills - search/list community skills."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    search = request.query.get("search") or None
    category = request.query.get("category") or None
    sort = request.query.get("sort", "popular")
    try:
        page = int(request.query.get("page", "1"))
        size = int(request.query.get("size", "20"))
    except ValueError:
        return _err("bad_request", "page and size must be integers", status=400)
    result = registry.list_skills(
        search=search, category=category, sort=sort, page=page, page_size=size,
        viewer_org_id=user.get("org_id"),
    )
    return web.json_response(result)


async def handle_community_get_skill(request: web.Request) -> web.Response:
    """GET /api/frontend/market/community/skills/{name} - skill detail."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    skill = registry.get_skill(name, viewer_org_id=user.get("org_id"))
    if not skill:
        return _err("not_found", "skill not found", status=404)
    return web.json_response(skill)


async def handle_community_install_skill(request: web.Request) -> web.Response:
    """POST /api/frontend/market/community/skills/{name}/install - install a skill."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    try:
        installed_name = await registry.install_skill(
            name, user_id=str(user["id"]), viewer_org_id=user.get("org_id")
        )
    except CommunityError as exc:
        status = {
            "not_found": 404,
            "no_install_url": 404,
            "forbidden": 403,
            "download_failed": 502,
            "empty_archive": 502,
            "hash_mismatch": 409,
        }.get(exc.code, 422)
        return _err(exc.code, exc.message, status=status)
    except Exception as exc:
        logger.warning("community_install failed: %s", exc)
        return _err("install_failed", str(exc), status=500)
    return web.json_response({"ok": True, "name": installed_name})


async def handle_community_get_categories(request: web.Request) -> web.Response:
    """GET /api/frontend/market/community/categories - list categories."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    categories = registry.get_categories()
    return web.json_response({"categories": categories})


async def handle_community_get_rankings(request: web.Request) -> web.Response:
    """GET /api/frontend/market/community/rankings - top skills by installs."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    period = request.query.get("period", "week")
    if period not in ("week", "month", "all"):
        return _err("bad_request", "period must be week|month|all", status=400)
    rankings = registry.get_rankings(period=period, viewer_org_id=user.get("org_id"))
    return web.json_response({"rankings": rankings})


async def handle_community_get_featured(request: web.Request) -> web.Response:
    """GET /api/frontend/market/community/featured - editor's picks."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    featured = registry.get_featured(viewer_org_id=user.get("org_id"))
    return web.json_response({"skills": featured})


# ─── Community Review Handlers ────────────────────────────────


async def handle_community_list_reviews(request: web.Request) -> web.Response:
    """GET /api/frontend/market/community/skills/{name}/reviews - list reviews."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    try:
        page = int(request.query.get("page", "1"))
        size = int(request.query.get("size", "10"))
    except ValueError:
        return _err("bad_request", "page and size must be integers", status=400)
    result = registry.list_reviews(name, page=page, page_size=size)
    return web.json_response(result)


async def handle_community_add_review(request: web.Request) -> web.Response:
    """POST /api/frontend/market/community/skills/{name}/reviews - submit a review."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    try:
        body = await request.json()
    except Exception as exc:
        return _err("bad_request", str(exc), status=400)
    rating = body.get("rating")
    comment = body.get("comment", "")
    if rating is None or not isinstance(rating, int):
        return _err("bad_request", "rating must be an integer", status=400)
    if not isinstance(comment, str):
        return _err("bad_request", "comment must be a string", status=400)
    try:
        review = registry.add_review(
            skill_name=name,
            user_id=str(user["id"]),
            rating=rating,
            comment=comment,
        )
    except CommunityError as exc:
        status = {"invalid_rating": 400, "skill_not_found": 404}.get(exc.code, 409)
        return _err(exc.code, exc.message, status=status)
    except Exception as exc:
        logger.warning("add_review failed: %s", exc)
        return _err("review_failed", str(exc), status=500)
    return web.json_response({"ok": True, "review": review})


async def handle_community_mark_helpful(request: web.Request) -> web.Response:
    """POST /api/frontend/market/community/reviews/{id}/helpful - mark review helpful."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    try:
        review_id = int(request.match_info["id"])
    except (ValueError, KeyError):
        return _err("bad_request", "review id must be an integer", status=400)
    ok = registry.mark_helpful(review_id=review_id, user_id=str(user["id"]))
    if not ok:
        return _err("not_found", "review not found", status=404)
    return web.json_response({"ok": True})


# ─── Community Publish Handlers ───────────────────────────────


async def handle_community_publish_skill(request: web.Request) -> web.Response:
    """POST /api/frontend/market/community/publish - publish a skill (multipart)."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)

    metadata = {}
    zip_bytes = b""

    ctype = (request.content_type or "").lower()
    if "multipart" in ctype:
        reader = await request.multipart()
        async for part in reader:
            if part.name == "metadata":
                raw = await part.read()
                try:
                    metadata = json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    return _err("bad_request", f"invalid metadata JSON: {exc}", status=400)
            elif part.name in ("file", "archive", "zip"):
                buf = bytearray()
                max_bytes = registry._install_max_bytes
                while True:
                    chunk = await part.read_chunk(64 * 1024)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        return _err("too_large", status=413)
                zip_bytes = bytes(buf)
    else:
        return _err("bad_request", "multipart/form-data required", status=400)

    if not zip_bytes:
        return _err("bad_request", "zip file is required", status=400)
    if not metadata.get("name"):
        return _err("bad_request", "metadata must include 'name'", status=400)

    # Write zip to temp file for registry.publish_skill
    try:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)
        row = registry.publish_skill(
            publisher=user["username"],
            metadata=metadata,
            zip_path=tmp_path,
            owner_org_id=user.get("org_id"),
        )
    except CommunityError as exc:
        status = {"duplicate_name": 409, "missing_name": 400, "no_org": 400}.get(exc.code, 422)
        return _err(exc.code, exc.message, status=status)
    except ValidationError as exc:
        return _err(exc.code, exc.message, status=422)
    except Exception as exc:
        logger.warning("publish_skill failed: %s", exc)
        return _err("publish_failed", str(exc), status=500)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    return web.json_response({"ok": True, "skill": row})


async def handle_community_my_skills(request: web.Request) -> web.Response:
    """GET /api/frontend/market/community/my-skills - list skills published by user."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    skills = registry.list_my_skills(publisher=user["username"])
    return web.json_response({"skills": skills, "total": len(skills)})


async def handle_community_update_skill(request: web.Request) -> web.Response:
    """PUT /api/frontend/market/community/skills/{name} - update published skill."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    try:
        body = await request.json()
    except Exception as exc:
        return _err("bad_request", str(exc), status=400)
    try:
        row = registry.update_skill(
            name=name, publisher=user["username"], updates=body
        )
    except CommunityError as exc:
        status = {"not_owner": 403, "no_fields": 400}.get(exc.code, 422)
        return _err(exc.code, exc.message, status=status)
    except Exception as exc:
        logger.warning("update_skill failed: %s", exc)
        return _err("update_failed", str(exc), status=500)
    if not row:
        return _err("forbidden", "not the publisher", status=403)
    return web.json_response({"ok": True, "skill": row})


async def handle_community_withdraw_skill(request: web.Request) -> web.Response:
    """DELETE /api/frontend/market/community/skills/{name} - withdraw published skill."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    ok = registry.withdraw_skill(name=name, publisher=user["username"])
    if not ok:
        return _err(
            "forbidden", "skill not found or you are not the publisher", status=403
        )
    return web.json_response({"ok": True})


# ─── Community Favorite Handlers ──────────────────────────────


async def handle_community_list_favorites(request: web.Request) -> web.Response:
    """GET /api/frontend/market/community/favorites - list user favorites."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    skills = registry.list_favorites(user_id=str(user["id"]))
    return web.json_response({"skills": skills, "total": len(skills)})


async def handle_community_add_favorite(request: web.Request) -> web.Response:
    """POST /api/frontend/market/community/favorites/{name} - add to favorites."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    ok = registry.add_favorite(user_id=str(user["id"]), skill_name=name)
    if not ok:
        return _err("add_favorite_failed", status=500)
    return web.json_response({"ok": True})


async def handle_community_remove_favorite(request: web.Request) -> web.Response:
    """DELETE /api/frontend/market/community/favorites/{name} - remove from favorites."""
    user = _get_current_user(request)
    if not user:
        return _err("unauthorized", status=401)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    ok = registry.remove_favorite(user_id=str(user["id"]), skill_name=name)
    if not ok:
        return _err("not_found", "favorite not found", status=404)
    return web.json_response({"ok": True})


# ─── Community Admin Moderation Handlers ────────────────


async def handle_community_pending(request: web.Request) -> web.Response:
    """GET /api/frontend/market/community/admin/pending - list skills awaiting review."""
    if _require_admin(request) is None:
        return _err("forbidden", "admin required", status=403)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    try:
        page = int(request.query.get("page", 1))
        page_size = int(request.query.get("page_size", 20))
    except ValueError:
        page, page_size = 1, 20
    result = registry.list_pending(page=page, page_size=page_size)
    return web.json_response(result)


async def handle_community_moderate_skill(request: web.Request) -> web.Response:
    """POST /api/frontend/market/community/admin/skills/{name}/moderate - approve/reject."""
    admin = _require_admin(request)
    if admin is None:
        return _err("forbidden", "admin required", status=403)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    try:
        body = await request.json()
    except Exception as exc:
        return _err("bad_request", str(exc), status=400)
    action = body.get("action", "")
    note = body.get("note", "")
    try:
        row = registry.moderate_skill(
            name=name, action=action, reviewer=admin["username"], note=note
        )
    except CommunityError as exc:
        status = {"not_found": 404, "invalid_action": 400}.get(exc.code, 422)
        return _err(exc.code, exc.message, status=status)
    except Exception as exc:
        logger.warning("moderate_skill failed: %s", exc)
        return _err("moderate_failed", str(exc), status=500)
    return web.json_response({"ok": True, "skill": row})


async def handle_community_feature_skill(request: web.Request) -> web.Response:
    """POST /api/frontend/market/community/admin/skills/{name}/feature - toggle featured."""
    if _require_admin(request) is None:
        return _err("forbidden", "admin required", status=403)
    registry = _get_community(request)
    if not registry:
        return _err("community_unavailable", status=503)
    name = request.match_info["name"]
    try:
        body = await request.json()
    except Exception as exc:
        return _err("bad_request", str(exc), status=400)
    featured = bool(body.get("featured", False))
    ok = registry.set_featured(name=name, featured=featured)
    if not ok:
        return _err("not_found", "skill not found", status=404)
    return web.json_response({"ok": True, "featured": featured})


# ─── Community Route Registration ─────────────────────────────


def register_community_routes(
    app: web.Application, registry: CommunityRegistry
) -> None:
    """Register community market routes onto the given aiohttp app."""
    app["community_registry"] = registry
    p = "/api/frontend/market/community"
    # Admin moderation (register before /skills/{name} dynamic segments)
    app.router.add_get(f"{p}/admin/pending", handle_community_pending)
    app.router.add_post(
        f"{p}/admin/skills/{{name}}/moderate", handle_community_moderate_skill
    )
    app.router.add_post(
        f"{p}/admin/skills/{{name}}/feature", handle_community_feature_skill
    )
    # Market
    app.router.add_get(f"{p}/skills", handle_community_list_skills)
    app.router.add_get(f"{p}/skills/{{name}}", handle_community_get_skill)
    app.router.add_post(f"{p}/skills/{{name}}/install", handle_community_install_skill)
    app.router.add_get(f"{p}/categories", handle_community_get_categories)
    app.router.add_get(f"{p}/rankings", handle_community_get_rankings)
    app.router.add_get(f"{p}/featured", handle_community_get_featured)
    # Reviews
    app.router.add_get(f"{p}/skills/{{name}}/reviews", handle_community_list_reviews)
    app.router.add_post(f"{p}/skills/{{name}}/reviews", handle_community_add_review)
    app.router.add_post(f"{p}/reviews/{{id}}/helpful", handle_community_mark_helpful)
    # Publish
    app.router.add_post(f"{p}/publish", handle_community_publish_skill)
    app.router.add_get(f"{p}/my-skills", handle_community_my_skills)
    app.router.add_put(f"{p}/skills/{{name}}", handle_community_update_skill)
    app.router.add_delete(f"{p}/skills/{{name}}", handle_community_withdraw_skill)
    # Favorites
    app.router.add_get(f"{p}/favorites", handle_community_list_favorites)
    app.router.add_post(f"{p}/favorites/{{name}}", handle_community_add_favorite)
    app.router.add_delete(f"{p}/favorites/{{name}}", handle_community_remove_favorite)

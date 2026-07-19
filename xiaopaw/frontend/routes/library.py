"""Library (file management) route handlers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from xiaopaw.frontend.routes.helpers import check_auth

logger = logging.getLogger(__name__)

# ── File type classification ─────────────────────────────────────────────────

_EXT_TYPE_MAP: dict[str, str] = {}
for _ext in (".docx", ".doc", ".md", ".txt", ".pdf"):
    _EXT_TYPE_MAP[_ext] = "document"
for _ext in (".pptx", ".ppt"):
    _EXT_TYPE_MAP[_ext] = "presentation"
for _ext in (".xlsx", ".xls", ".csv"):
    _EXT_TYPE_MAP[_ext] = "spreadsheet"
for _ext in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".bmp"):
    _EXT_TYPE_MAP[_ext] = "image"
for _ext in (".drawio", ".vsdx"):
    _EXT_TYPE_MAP[_ext] = "diagram"

_TYPE_LABELS: dict[str, str] = {
    "document": "文档",
    "presentation": "幻灯片",
    "spreadsheet": "表格",
    "image": "图片",
    "diagram": "图表",
    "other": "其他",
}

_SKIP_NAMES = frozenset({".DS_Store", "__pycache__", ".git", ".gitkeep"})


def _classify_file(ext: str) -> tuple[str, str]:
    """Return (type_key, type_label) for a file extension."""
    type_key = _EXT_TYPE_MAP.get(ext.lower(), "other")
    return type_key, _TYPE_LABELS.get(type_key, "其他")


def _scan_session_outputs(workspace_path: Path) -> dict[str, list[dict]]:
    """Scan all sessions/*/outputs/ and return {session_id: [file_info, ...]}."""
    sessions_dir = workspace_path / "sessions"
    result: dict[str, list[dict]] = {}

    if not sessions_dir.is_dir():
        return result

    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir() or session_dir.name in _SKIP_NAMES:
            continue
        session_id = session_dir.name
        outputs_dir = session_dir / "outputs"
        if not outputs_dir.is_dir():
            continue

        files: list[dict] = []
        for entry in outputs_dir.iterdir():
            if not entry.is_file() or entry.name in _SKIP_NAMES:
                continue
            try:
                st = entry.stat()
                ext = entry.suffix.lower()
                type_key, type_label = _classify_file(ext)
                files.append({
                    "name": entry.name,
                    "path": f"/sessions/{session_id}/outputs/{entry.name}",
                    "type": type_label,
                    "type_key": type_key,
                    "ext": ext,
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(
                        st.st_mtime, tz=timezone.utc
                    ).isoformat(),
                })
            except OSError:
                pass

        if files:
            result[session_id] = files

    return result


def _get_session_titles(request: web.Request, session_ids: list[str]) -> dict[str, str]:
    """Fetch session titles from PGStore, fallback to session_id."""
    from xiaopaw.frontend.store import PGStore

    titles: dict[str, str] = {sid: sid for sid in session_ids}

    pg_store: PGStore | None = request.app.get("pg_store")
    if not pg_store or not session_ids:
        return titles

    try:
        import psycopg2
        import psycopg2.extras

        with psycopg2.connect(pg_store._dsn) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, title FROM sessions WHERE id = ANY(%s)",
                    (session_ids,),
                )
                for row in cur.fetchall():
                    if row.get("title"):
                        titles[row["id"]] = row["title"]
    except Exception as exc:
        logger.warning("library: failed to fetch session titles: %s", exc)

    return titles


# ── Favorites persistence ────────────────────────────────────────────────────


def _load_favorites(workspace_path: Path) -> set[str]:
    """Load favorite file paths from JSON."""
    fav_file = workspace_path.parent / "library" / "favorites.json"
    if fav_file.is_file():
        try:
            data = json.loads(fav_file.read_text(encoding="utf-8"))
            return set(data.get("paths", []))
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def _save_favorites(workspace_path: Path, favorites: set[str]) -> None:
    """Save favorite file paths to JSON."""
    lib_dir = workspace_path.parent / "library"
    lib_dir.mkdir(parents=True, exist_ok=True)
    fav_file = lib_dir / "favorites.json"
    fav_file.write_text(
        json.dumps({"paths": sorted(favorites)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── handlers ─────────────────────────────────────────────────────────────────


async def handle_library_files(request: web.Request) -> web.Response:
    """GET /api/frontend/library/files"""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    workspace_dir_str = request.app.get("workspace_dir", "")
    if not workspace_dir_str:
        return web.json_response({"error": "workspace_dir not configured"}, status=500)

    workspace_path = Path(workspace_dir_str).resolve()

    # Query params
    filter_type = request.query.get("type", "all").strip()
    search_kw = request.query.get("search", "").strip().lower()
    show_favs = request.query.get("favorites", "").strip() == "true"
    sort_by = request.query.get("sort", "mtime").strip()
    sort_order = request.query.get("order", "desc").strip()

    all_files = _scan_session_outputs(workspace_path)

    if not all_files:
        return web.json_response({"groups": [], "total": 0})

    session_ids = list(all_files.keys())
    titles = _get_session_titles(request, session_ids)

    favorites = _load_favorites(workspace_path) if show_favs else set()

    groups: list[dict] = []
    total = 0

    for session_id, files in all_files.items():
        filtered = files
        if filter_type and filter_type != "all":
            filtered = [f for f in filtered if f["type_key"] == filter_type]
        if search_kw:
            filtered = [
                f for f in filtered
                if search_kw in f["name"].lower()
                or search_kw in titles.get(session_id, "").lower()
            ]
        if show_favs:
            filtered = [f for f in filtered if f["path"] in favorites]

        if not filtered:
            continue

        reverse = sort_order != "asc"
        if sort_by == "size":
            filtered.sort(key=lambda f: f["size"], reverse=reverse)
        elif sort_by == "name":
            filtered.sort(key=lambda f: f["name"].lower(), reverse=reverse)
        else:
            filtered.sort(key=lambda f: f["mtime"], reverse=reverse)

        type_counts: dict[str, int] = {}
        for f in filtered:
            type_counts[f["type_key"]] = type_counts.get(f["type_key"], 0) + 1
        main_type = max(type_counts, key=type_counts.get) if type_counts else "other"

        groups.append({
            "session_id": session_id,
            "title": titles.get(session_id, session_id),
            "icon": main_type,
            "file_count": len(filtered),
            "files": filtered,
        })
        total += len(filtered)

    groups.sort(
        key=lambda g: max((f["mtime"] for f in g["files"]), default=""),
        reverse=True,
    )

    return web.json_response({
        "groups": groups,
        "total": total,
        "type_options": ["all", "document", "presentation", "spreadsheet", "image", "diagram", "other"],
    })


async def handle_library_favorites_get(request: web.Request) -> web.Response:
    """GET /api/frontend/library/favorites"""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    workspace_dir_str = request.app.get("workspace_dir", "")
    if not workspace_dir_str:
        return web.json_response({"error": "workspace_dir not configured"}, status=500)

    workspace_path = Path(workspace_dir_str).resolve()
    favorites = _load_favorites(workspace_path)
    return web.json_response({"paths": sorted(favorites)})


async def handle_library_favorites_update(request: web.Request) -> web.Response:
    """POST /api/frontend/library/favorites"""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    workspace_dir_str = request.app.get("workspace_dir", "")
    if not workspace_dir_str:
        return web.json_response({"error": "workspace_dir not configured"}, status=500)

    workspace_path = Path(workspace_dir_str).resolve()

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=422)

    path = body.get("path", "").strip()
    action = body.get("action", "").strip()
    if not path or action not in ("add", "remove"):
        return web.json_response(
            {"error": "path and action (add|remove) required"}, status=422
        )

    favorites = _load_favorites(workspace_path)
    if action == "add":
        favorites.add(path)
    else:
        favorites.discard(path)

    _save_favorites(workspace_path, favorites)
    return web.json_response({"success": True, "action": action, "path": path})


def register_library_routes(app: web.Application) -> None:
    """Register library (file management) routes."""
    app.router.add_get("/api/frontend/library/files", handle_library_files)
    app.router.add_get("/api/frontend/library/favorites", handle_library_favorites_get)
    app.router.add_post("/api/frontend/library/favorites", handle_library_favorites_update)

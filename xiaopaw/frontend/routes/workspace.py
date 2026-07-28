"""Workspace route handlers: file download, tree, read, write."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from .helpers import check_auth, get_user_workspace_path

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────
_SANDBOX_WORKSPACE_PREFIX = "/workspace/"
_MAX_READ_SIZE = 1 * 1024 * 1024  # 1 MB
_TEXT_EXTENSIONS = frozenset({
    ".md", ".txt", ".json", ".js", ".ts", ".py",
    ".yaml", ".yml", ".toml", ".csv", ".xml",
    ".html", ".css", ".sh", ".env", ".example",
})


# ── helpers ──────────────────────────────────────────────────────────────────


def _get_workspace(request: web.Request) -> Path | web.Response:
    """Return resolved user-level workspace path or an error response."""
    return get_user_workspace_path(request)


def _safe_resolve(workspace_path: Path, raw_path: str) -> tuple[Path, str] | web.Response:
    """Resolve raw_path inside workspace with traversal protection."""
    clean = raw_path.lstrip("/")
    resolved = (workspace_path / clean).resolve()
    if not str(resolved).startswith(str(workspace_path) + os.sep) and resolved != workspace_path:
        logger.warning("workspace: path traversal blocked: %s -> %s", raw_path, resolved)
        return web.json_response({"error": "invalid path"}, status=400)
    return resolved, clean


def _build_dir_tree(dir_path: Path, root_path: Path, rel_path: str, max_depth: int) -> dict:
    """Build a directory tree node with children up to max_depth levels deep."""
    parts = rel_path.split("/") if rel_path else []
    name = parts[-1] if parts else ""

    node: dict = {
        "name": name,
        "type": "dir",
        "path": "/" + rel_path if rel_path else "/",
    }

    if max_depth < 0:
        return node

    children: list[dict] = []
    try:
        entries = sorted(os.scandir(dir_path), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        entries = []

    for entry in entries:
        child_rel = f"{rel_path}/{entry.name}" if rel_path else entry.name

        if entry.is_dir():
            child = _build_dir_tree(Path(entry.path), root_path, child_rel, max_depth - 1)
            children.append(child)
        elif entry.is_file():
            try:
                st = entry.stat()
                children.append({
                    "name": entry.name,
                    "type": "file",
                    "path": "/" + child_rel,
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                })
            except OSError:
                pass

    node["children"] = children
    return node


# ── handlers ─────────────────────────────────────────────────────────────────


async def handle_file_download(request: web.Request) -> web.Response:
    """GET /api/frontend/files/download?path=/workspace/sessions/xxx/xxx.pptx"""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    raw_path = request.query.get("path", "").strip()
    if not raw_path:
        return web.json_response({"error": "missing 'path' query param"}, status=422)

    ws = get_user_workspace_path(request)
    if isinstance(ws, web.Response):
        return ws

    # Resolve sandbox /workspace/ prefix to the user workspace dir
    if raw_path.startswith(_SANDBOX_WORKSPACE_PREFIX):
        relative = raw_path[len(_SANDBOX_WORKSPACE_PREFIX):]
    elif raw_path.startswith("/"):
        return web.json_response({"error": "path must start with /workspace/"}, status=400)
    else:
        relative = raw_path

    resolved = (ws / relative).resolve()

    if not str(resolved).startswith(str(ws) + os.sep) and resolved != ws:
        logger.warning("frontend: path traversal blocked: %s -> %s", raw_path, resolved)
        return web.json_response({"error": "invalid path"}, status=400)

    # 用户级工作空间未命中时回退到全局工作空间（资料库任务成果位于全局 sessions/ 目录）
    if not resolved.is_file():
        workspace_dir = request.app.get("workspace_dir", "")
        if workspace_dir:
            base = Path(workspace_dir).resolve()
            fallback = (base / relative).resolve()
            if (str(fallback).startswith(str(base) + os.sep) or fallback == base) and fallback.is_file():
                resolved = fallback

    if not resolved.is_file():
        return web.json_response({"error": "file not found"}, status=404)

    return web.FileResponse(str(resolved))


async def handle_workspace_tree(request: web.Request) -> web.Response:
    """GET /api/frontend/workspace/tree?dir=/sessions"""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    raw_dir = request.query.get("dir", "").strip()
    ws = _get_workspace(request)
    if isinstance(ws, web.Response):
        return ws

    if not raw_dir or raw_dir == "/":
        resolved = ws
        rel_path = ""
    else:
        result = _safe_resolve(ws, raw_dir)
        if isinstance(result, web.Response):
            return result
        resolved, rel_path = result
        if not resolved.is_dir():
            return web.json_response({"error": "not a directory"}, status=400)

    tree = _build_dir_tree(resolved, ws, rel_path, max_depth=3)
    return web.json_response(tree)


async def handle_workspace_read(request: web.Request) -> web.Response:
    """GET /api/frontend/workspace/read?path=/soul.md"""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    raw_path = request.query.get("path", "").strip()
    if not raw_path:
        return web.json_response({"error": "missing path"}, status=422)

    ws = _get_workspace(request)
    if isinstance(ws, web.Response):
        return ws

    result = _safe_resolve(ws, raw_path)
    if isinstance(result, web.Response):
        return result
    resolved, _ = result

    if not resolved.is_file():
        return web.json_response({"error": "file not found"}, status=404)

    st = resolved.stat()
    ext = resolved.suffix.lower()
    if ext in _TEXT_EXTENSIONS:
        try:
            if st.st_size > _MAX_READ_SIZE:
                return web.json_response(
                    {"error": "file too large", "size": st.st_size}, status=413
                )
            content = resolved.read_text(encoding="utf-8")
            return web.json_response({"content": content, "path": raw_path, "size": st.st_size})
        except (UnicodeDecodeError, OSError) as exc:
            logger.warning("workspace read text failed for %s: %s", raw_path, exc)

    return web.json_response({"binary": True, "size": st.st_size, "path": raw_path})


async def handle_workspace_write(request: web.Request) -> web.Response:
    """POST /api/frontend/workspace/write?path=/soul.md"""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    raw_path = request.query.get("path", "").strip()
    if not raw_path:
        return web.json_response({"error": "missing path"}, status=422)

    if not raw_path.lower().endswith(".md"):
        return web.json_response({"error": "only .md files are writable"}, status=403)

    ws = _get_workspace(request)
    if isinstance(ws, web.Response):
        return ws

    result = _safe_resolve(ws, raw_path)
    if isinstance(result, web.Response):
        return result
    resolved, clean = result

    # Only allow writing at workspace root level (not in sessions/)
    if "/" in clean:
        return web.json_response({"error": "only root-level .md files are writable"}, status=403)

    try:
        body = await request.json()
        content = body.get("content", "")
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=422)

    resolved.write_text(content, encoding="utf-8")
    return web.json_response({"success": True, "path": raw_path})


def register_workspace_routes(app: web.Application) -> None:
    """Register workspace/file routes."""
    app.router.add_get("/api/frontend/files/download", handle_file_download)
    app.router.add_get("/api/frontend/workspace/tree", handle_workspace_tree)
    app.router.add_get("/api/frontend/workspace/read", handle_workspace_read)
    app.router.add_post("/api/frontend/workspace/write", handle_workspace_write)

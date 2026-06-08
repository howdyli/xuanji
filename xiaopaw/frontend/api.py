"""REST API endpoints for the frontend."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from xiaopaw.api.capture_sender import CaptureSender
from xiaopaw.frontend.store import PGStore
from xiaopaw.models import InboundMessage
from xiaopaw.observability.trace import new_trace_id

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

async def handle_file_download(request: web.Request) -> web.Response:
    """GET /api/frontend/files/download?path=/workspace/sessions/xxx/xxx.pptx

    Resolves sandbox-side ``/workspace/`` path to the host ``workspace_dir``,
    validates the result stays inside the workspace (path traversal protection),
    and streams the file to the client.
    """
    raw_path = request.query.get("path", "").strip()
    if not raw_path:
        return web.json_response({"error": "missing 'path' query param"}, status=422)

    workspace_dir = request.app.get("workspace_dir", "")
    if not workspace_dir:
        return web.json_response({"error": "workspace_dir not configured"}, status=500)

    # Resolve sandbox /workspace/ prefix to the host workspace_dir
    if raw_path.startswith(_SANDBOX_WORKSPACE_PREFIX):
        relative = raw_path[len(_SANDBOX_WORKSPACE_PREFIX):]
    elif raw_path.startswith("/"):
        # Extra guard: reject absolute paths that don't go through /workspace/
        return web.json_response({"error": "path must start with /workspace/"}, status=400)
    else:
        relative = raw_path

    resolved = (Path(workspace_dir).resolve() / relative).resolve()
    workspace_resolved = Path(workspace_dir).resolve()

    # Path traversal protection: must stay inside workspace_dir
    if not str(resolved).startswith(str(workspace_resolved) + os.sep) and resolved != workspace_resolved:
        logger.warning("frontend: path traversal blocked: %s -> %s", raw_path, resolved)
        return web.json_response({"error": "invalid path"}, status=400)

    if not resolved.is_file():
        return web.json_response({"error": "file not found"}, status=404)

    return web.FileResponse(str(resolved))


# ── workspace handlers ──────────────────────────────────────────────────

async def handle_workspace_tree(request: web.Request) -> web.Response:
    """GET /api/frontend/workspace/tree?dir=/sessions

    Returns a directory tree rooted at the requested path.
    The ``dir`` param is optional; defaults to workspace root.
    """
    raw_dir = request.query.get("dir", "").strip()
    workspace_dir_str = request.app.get("workspace_dir", "")
    if not workspace_dir_str:
        return web.json_response({"error": "workspace_dir not configured"}, status=500)

    workspace_path = Path(workspace_dir_str).resolve()

    if not raw_dir or raw_dir == "/":
        resolved = workspace_path
        rel_path = ""
    else:
        clean = raw_dir.lstrip("/")
        resolved = (workspace_path / clean).resolve()
        if not str(resolved).startswith(str(workspace_path) + os.sep):
            return web.json_response({"error": "invalid path"}, status=400)
        if not resolved.is_dir():
            return web.json_response({"error": "not a directory"}, status=400)
        rel_path = clean

    tree = _build_dir_tree(resolved, workspace_path, rel_path, max_depth=3)
    return web.json_response(tree)


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


async def handle_workspace_read(request: web.Request) -> web.Response:
    """GET /api/frontend/workspace/read?path=/soul.md

    Read a file from the workspace. Text files return content inline;
    binary files return a flag with size so the frontend can show a download link.
    """
    raw_path = request.query.get("path", "").strip()
    if not raw_path:
        return web.json_response({"error": "missing path"}, status=422)

    workspace_dir_str = request.app.get("workspace_dir", "")
    if not workspace_dir_str:
        return web.json_response({"error": "workspace_dir not configured"}, status=500)

    workspace_path = Path(workspace_dir_str).resolve()
    clean = raw_path.lstrip("/")
    resolved = (workspace_path / clean).resolve()

    if not str(resolved).startswith(str(workspace_path) + os.sep):
        return web.json_response({"error": "invalid path"}, status=400)

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
    """POST /api/frontend/workspace/write?path=/soul.md

    Write content to a root-level .md file in the workspace.
    Body: {"content": "..."}
    Only .md files at workspace root are writable (not in sessions/).
    """
    raw_path = request.query.get("path", "").strip()
    if not raw_path:
        return web.json_response({"error": "missing path"}, status=422)

    if not raw_path.lower().endswith(".md"):
        return web.json_response({"error": "only .md files are writable"}, status=403)

    clean = raw_path.lstrip("/")
    if "/" in clean:
        return web.json_response({"error": "only root-level .md files are writable"}, status=403)

    workspace_dir_str = request.app.get("workspace_dir", "")
    if not workspace_dir_str:
        return web.json_response({"error": "workspace_dir not configured"}, status=500)

    workspace_path = Path(workspace_dir_str).resolve()
    resolved = (workspace_path / clean).resolve()

    if not str(resolved).startswith(str(workspace_path) + os.sep):
        return web.json_response({"error": "invalid path"}, status=400)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=422)

    content = body.get("content", "")
    try:
        resolved.write_text(content, encoding="utf-8")
        logger.info("workspace write: %s (%d chars)", raw_path, len(content))
        return web.json_response({"success": True})
    except OSError as exc:
        logger.warning("workspace write failed for %s: %s", raw_path, exc)
        return web.json_response({"error": str(exc)}, status=500)


def _check_auth(request: web.Request) -> bool:
    """Check Bearer token — session token (UserAuth) or static fallback."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        # No auth header: allow only if no token configured and no user_auth
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


def _get_current_user(request: web.Request) -> dict | None:
    """Extract current user from the request's Bearer token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    bearer = auth[7:]
    user_auth = request.app.get("user_auth")
    if not user_auth:
        return None
    return user_auth.get_user_by_token(bearer)


# ── auth handlers ────────────────────────────────────────────────────

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
        token, user = user_auth.login(username, password)
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
    user = _get_current_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response({"user": user})


async def handle_auth_update_profile(request: web.Request) -> web.Response:
    """PUT /api/frontend/auth/profile — update current user's profile."""
    user = _get_current_user(request)
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
    user = _get_current_user(request)
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


# ── expert handlers ────────────────────────────────────────────────────


async def handle_experts_list(request: web.Request) -> web.Response:
    """GET /api/frontend/experts — list all experts (supports ?category= filter)."""
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("expert_registry")
    if not registry:
        return web.json_response({"experts": [], "total": 0})
    category = request.query.get("category", "").strip()
    experts = registry.list_all(category=category)
    return web.json_response({"experts": experts, "total": len(experts)})


async def handle_experts_categories(request: web.Request) -> web.Response:
    """GET /api/frontend/experts/categories — list all categories with counts."""
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("expert_registry")
    if not registry:
        return web.json_response({"categories": []})
    categories = registry.list_categories()
    return web.json_response({"categories": categories})


async def handle_expert_detail(request: web.Request) -> web.Response:
    """GET /api/frontend/experts/{name} — single expert detail."""
    if not _check_auth(request):
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
    if not _check_auth(request):
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
    if not _check_auth(request):
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
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("expert_registry")
    if not registry:
        return web.json_response({"error": "expert_registry unavailable"}, status=503)
    name = request.match_info.get("name", "")
    if registry.delete(name):
        return web.json_response({"success": True})
    return web.json_response({"error": "not_found"}, status=404)


# ── automation handlers ─────────────────────────────────────────────────


async def handle_automation_tasks_list(request: web.Request) -> web.Response:
    """GET /api/frontend/automation/tasks — list all tasks."""
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("automation_registry")
    if not registry:
        return web.json_response({"tasks": [], "total": 0})
    tasks = registry.list_tasks()
    return web.json_response({"tasks": tasks, "total": len(tasks)})


async def handle_automation_task_create(request: web.Request) -> web.Response:
    """POST /api/frontend/automation/tasks — create task (supports from_template)."""
    if not _check_auth(request):
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
    if not _check_auth(request):
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
    if not _check_auth(request):
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
    if not _check_auth(request):
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
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    registry = request.app.get("automation_registry")
    if not registry:
        return web.json_response({"templates": []})
    return web.json_response({"templates": registry.list_templates()})


async def handle_message(request: web.Request) -> web.Response:
    """POST /api/frontend/message - send a message to the AI.

    Request body:
    {
        "content": "用户消息",
        "session_id": "可选，继续已有会话",
        "routing_key": "p2p:web_user"  (可选，默认 p2p:web_user),
        "expert": "可选，专家标识（如 coder）"
    }
    """
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        body = await request.json()
        content = body.get("content", "").strip()
        routing_key = body.get("routing_key", "p2p:web_user")
        session_id_hint = body.get("session_id", "")
        expert_name = body.get("expert", "").strip()
        if not content:
            return web.json_response({"error": "content is required"}, status=422)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=422)

    runner = request.app.get("runner")
    sender = request.app.get("sender")
    session_mgr = request.app.get("session_mgr")
    pg_store: PGStore | None = request.app.get("pg_store")

    if not runner or not session_mgr:
        return web.json_response({"error": "backend not ready"}, status=503)

    # Activate existing session if session_id_hint provided
    if session_id_hint:
        existing = await session_mgr.get_session_by_id(session_id_hint)
        if existing:
            await session_mgr.activate_session(session_id_hint, routing_key)

    # Create or reuse session
    session = await session_mgr.get_or_create(routing_key)
    session_id = session.id

    msg_id = f"web_{uuid.uuid4().hex[:12]}"

    # Inject expert system prompt if specified
    if expert_name:
        expert_reg = request.app.get("expert_registry")
        if expert_reg:
            expert = expert_reg.get(expert_name)
            if expert and expert.get("system_prompt"):
                content = f"[Expert: {expert['display_name']}]\n{expert['system_prompt']}\n\n---\n\n{content}"

    inbound = InboundMessage(
        routing_key=routing_key,
        content=content,
        msg_id=msg_id,
        sender_id="web_user",
        ts=int(time.time() * 1000),
        trace_id=new_trace_id(),
    )

    # Register a future to capture the AI reply
    future = None
    if isinstance(sender, CaptureSender):
        future = sender.register(msg_id)

    # Dispatch to runner
    start = time.monotonic()
    await runner.dispatch(inbound)

    # Wait for reply (only works with CaptureSender)
    reply = ""
    if future:
        try:
            reply = await future
        except Exception as exc:
            logger.warning("frontend: reply capture failed: %s", exc)
            reply = "[error]"

    duration_ms = int((time.monotonic() - start) * 1000)

    # Persist to PostgreSQL (async, fire-and-forget)
    if pg_store:
        await pg_store.save_conversation(msg_id, session_id, routing_key, "user", content)
        await pg_store.save_conversation(
            f"{msg_id}_reply", session_id, routing_key, "assistant", reply
        )
        await pg_store.save_session(
            session_id, routing_key,
            title=content[:80],
            message_count=session.message_count + 2,
        )

    return web.json_response({
        "msg_id": msg_id,
        "reply": reply,
        "session_id": session_id,
        "duration_ms": duration_ms,
        "trace_id": inbound.trace_id,
    })


async def handle_sessions(request: web.Request) -> web.Response:
    """GET /api/frontend/sessions - list active sessions."""
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    # Try PGStore first (has titles, correct updated_at)
    pg_store: PGStore | None = request.app.get("pg_store")
    if pg_store:
        try:
            import psycopg2
            import psycopg2.extras
            with psycopg2.connect(pg_store._dsn) as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """SELECT id, routing_key, title, message_count, created_at, updated_at
                           FROM sessions ORDER BY updated_at DESC LIMIT 50"""
                    )
                    sessions = list(cur.fetchall())
                    # Convert datetime to ISO string
                    for s in sessions:
                        for k in ("created_at", "updated_at"):
                            if s.get(k):
                                s[k] = s[k].isoformat()
                    return web.json_response({"sessions": sessions})
        except Exception as exc:
            logger.warning("frontend: failed to fetch sessions from PG: %s", exc)

    # Fallback: list from SessionManager (JSONL-based)
    session_mgr = request.app.get("session_mgr")
    if session_mgr:
        return web.json_response({"sessions": session_mgr.list_all_sessions()})

    return web.json_response({"sessions": []})


async def handle_session_messages(request: web.Request) -> web.Response:
    """GET /api/frontend/sessions/{session_id}/messages - get session history."""
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    session_id = request.match_info.get("session_id", "")
    if not session_id:
        return web.json_response({"error": "missing session_id"}, status=422)

    session_mgr = request.app.get("session_mgr")
    if not session_mgr:
        return web.json_response({"error": "backend not ready"}, status=503)

    try:
        entries = await session_mgr.load_history(session_id)
        messages = []
        from datetime import datetime, timezone
        for e in entries:
            messages.append({
                "id": f"{session_id}_{e.ts}",
                "role": e.role,
                "content": e.content,
                "timestamp": datetime.fromtimestamp(e.ts / 1000, tz=timezone.utc).isoformat() if e.ts else None,
            })
        return web.json_response({"messages": messages})
    except Exception as exc:
        logger.warning("frontend: load_history failed for %s: %s", session_id, exc)
        return web.json_response({"error": str(exc)}, status=500)


# ── library (file management) handlers ─────────────────────────────────

# File type classification
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

# Hidden/system files to skip
_SKIP_NAMES = frozenset({".DS_Store", "__pycache__", ".git", ".gitkeep"})


def _classify_file(ext: str) -> tuple[str, str]:
    """Return (type_key, type_label) for a file extension."""
    type_key = _EXT_TYPE_MAP.get(ext.lower(), "other")
    return type_key, _TYPE_LABELS.get(type_key, "其他")


def _scan_session_outputs(
    workspace_path: Path,
) -> dict[str, list[dict]]:
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


def _get_session_titles(
    request: web.Request, session_ids: list[str]
) -> dict[str, str]:
    """Fetch session titles from PGStore, fallback to session_id."""
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


# Favorites persistence
_FAVORITES_FILE = "data/library/favorites.json"


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


async def handle_library_files(request: web.Request) -> web.Response:
    """GET /api/frontend/library/files

    Returns files grouped by session with filtering and sorting.
    """
    if not _check_auth(request):
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

    # Scan files
    all_files = _scan_session_outputs(workspace_path)

    if not all_files:
        return web.json_response({"groups": [], "total": 0})

    # Fetch session titles
    session_ids = list(all_files.keys())
    titles = _get_session_titles(request, session_ids)

    # Load favorites
    favorites = _load_favorites(workspace_path) if show_favs else set()

    # Build groups with filtering
    groups: list[dict] = []
    total = 0

    for session_id, files in all_files.items():
        # Apply filters
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

        # Sort files within group
        reverse = sort_order != "asc"
        if sort_by == "size":
            filtered.sort(key=lambda f: f["size"], reverse=reverse)
        elif sort_by == "name":
            filtered.sort(key=lambda f: f["name"].lower(), reverse=reverse)
        else:  # mtime
            filtered.sort(key=lambda f: f["mtime"], reverse=reverse)

        # Determine group icon (most common type in this group)
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

    # Sort groups by latest file mtime
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
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    workspace_dir_str = request.app.get("workspace_dir", "")
    if not workspace_dir_str:
        return web.json_response({"error": "workspace_dir not configured"}, status=500)

    workspace_path = Path(workspace_dir_str).resolve()
    favorites = _load_favorites(workspace_path)
    return web.json_response({"paths": sorted(favorites)})


async def handle_library_favorites_update(request: web.Request) -> web.Response:
    """POST /api/frontend/library/favorites

    Body: {"path": "...", "action": "add|remove"}
    """
    if not _check_auth(request):
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


async def handle_config(request: web.Request) -> web.Response:
    """GET /api/frontend/config - get frontend configuration."""
    return web.json_response({
        "app_name": "玄机",
        "version": "2.0.0",
        "features": {
            "chat": True,
            "sessions": True,
            "settings": True,
        },
    })


# ── channel management handlers ──────────────────────────────────


def _get_channel_mgr(request: web.Request):
    """Helper to get channel_manager from app."""
    return request.app.get("channel_manager")


async def handle_channels_list(request: web.Request) -> web.Response:
    """GET /api/frontend/channels — list all LLM channels."""
    if not _check_auth(request):
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
            "api_key_preview": _mask_key_display(ch.api_key),
        })
    return web.json_response({"channels": channels})


async def handle_channel_create(request: web.Request) -> web.Response:
    """POST /api/frontend/channels — add a new LLM channel."""
    if not _check_auth(request):
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
    if not _check_auth(request):
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

    # Update fields
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
    if not _check_auth(request):
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
    if not _check_auth(request):
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
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    mgr = _get_channel_mgr(request)
    if not mgr:
        return web.json_response({"error": "channel manager not configured"}, status=503)

    name = request.match_info["name"]
    models = await mgr.fetch_models(name)
    return web.json_response({"models": models})


async def handle_channels_health(request: web.Request) -> web.Response:
    """GET /api/frontend/channels/health — health summary for all channels."""
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    mgr = _get_channel_mgr(request)
    if not mgr:
        return web.json_response({"health": {}})
    return web.json_response({"health": mgr.get_health_summary()})


def _mask_key_display(key: str) -> str:
    """Mask API key for display."""
    if not key or len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def register_routes(app: web.Application) -> None:
    """Register frontend API routes."""
    # Auth
    app.router.add_post("/api/frontend/auth/register", handle_auth_register)
    app.router.add_post("/api/frontend/auth/login", handle_auth_login)
    app.router.add_post("/api/frontend/auth/logout", handle_auth_logout)
    app.router.add_get("/api/frontend/auth/me", handle_auth_me)
    app.router.add_put("/api/frontend/auth/profile", handle_auth_update_profile)
    app.router.add_post("/api/frontend/auth/change-password", handle_auth_change_password)
    # Files
    app.router.add_get("/api/frontend/files/download", handle_file_download)
    app.router.add_get("/api/frontend/workspace/tree", handle_workspace_tree)
    app.router.add_get("/api/frontend/workspace/read", handle_workspace_read)
    app.router.add_post("/api/frontend/workspace/write", handle_workspace_write)
    app.router.add_get("/api/frontend/sessions", handle_sessions)
    app.router.add_get("/api/frontend/sessions/{session_id}/messages", handle_session_messages)
    app.router.add_post("/api/frontend/message", handle_message)
    app.router.add_get("/api/frontend/config", handle_config)
    # Channels (LLM Provider Management)
    app.router.add_get("/api/frontend/channels", handle_channels_list)
    app.router.add_post("/api/frontend/channels", handle_channel_create)
    app.router.add_put("/api/frontend/channels/{name}", handle_channel_update)
    app.router.add_delete("/api/frontend/channels/{name}", handle_channel_delete)
    app.router.add_post("/api/frontend/channels/{name}/test", handle_channel_test)
    app.router.add_post("/api/frontend/channels/{name}/fetch-models", handle_channel_fetch_models)
    app.router.add_get("/api/frontend/channels/health", handle_channels_health)
    # Library (File Management)
    app.router.add_get("/api/frontend/library/files", handle_library_files)
    app.router.add_get("/api/frontend/library/favorites", handle_library_favorites_get)
    app.router.add_post("/api/frontend/library/favorites", handle_library_favorites_update)
    # Experts
    app.router.add_get("/api/frontend/experts", handle_experts_list)
    app.router.add_get("/api/frontend/experts/categories", handle_experts_categories)
    app.router.add_get("/api/frontend/experts/{name}", handle_expert_detail)
    app.router.add_post("/api/frontend/experts", handle_expert_create)
    app.router.add_put("/api/frontend/experts/{name}", handle_expert_update)
    app.router.add_delete("/api/frontend/experts/{name}", handle_expert_delete)
    # Automation
    app.router.add_get("/api/frontend/automation/tasks", handle_automation_tasks_list)
    app.router.add_post("/api/frontend/automation/tasks", handle_automation_task_create)
    app.router.add_put("/api/frontend/automation/tasks/{id}", handle_automation_task_update)
    app.router.add_delete("/api/frontend/automation/tasks/{id}", handle_automation_task_delete)
    app.router.add_patch("/api/frontend/automation/tasks/{id}/toggle", handle_automation_task_toggle)
    app.router.add_get("/api/frontend/automation/templates", handle_automation_templates)

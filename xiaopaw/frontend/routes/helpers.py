"""Shared helpers for frontend route handlers."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path

from aiohttp import web

logger = logging.getLogger(__name__)


# ── Auth helpers ─────────────────────────────────────────────────────────────


def check_auth(request: web.Request) -> bool:
    """Check Bearer token -- session token (UserAuth) or static fallback."""
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


def require_auth(request: web.Request) -> web.Response | None:
    """Return 401 response if auth fails, or None if authorized."""
    if not check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return None


def get_current_user(request: web.Request) -> dict | None:
    """Extract current user from the request's Bearer token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    bearer = auth[7:]
    user_auth = request.app.get("user_auth")
    if not user_auth:
        return None
    return user_auth.get_user_by_token(bearer)


def get_routing_key_from_request(request: web.Request) -> str:
    """从认证用户构造 routing_key，忽略前端传入值。未认证回退到 p2p:web_user。"""
    user = get_current_user(request)
    username = user.get("username") if user else None
    return f"p2p:web_{username}" if username else "p2p:web_user"


async def list_sessions_for_user(pg_store, routing_key: str) -> list[dict]:
    """查询指定用户的会话列表，按 routing_key 过滤。"""
    if not pg_store:
        return []
    try:
        import psycopg2
        import psycopg2.extras
        with psycopg2.connect(pg_store._dsn) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, routing_key, title, message_count, created_at, updated_at
                       FROM sessions WHERE routing_key = %s
                          OR routing_key = 'p2p:web_user'
                       ORDER BY updated_at DESC LIMIT 50""",
                    (routing_key,),
                )
                sessions = list(cur.fetchall())
                for s in sessions:
                    for k in ("created_at", "updated_at"):
                        if s.get(k):
                            s[k] = s[k].isoformat()
                return sessions
    except Exception as exc:
        logger.warning("list_sessions_for_user failed: %s", exc)
        return []


# ── Workspace path helpers ──


def resolve_safe_path(
    workspace_path: Path, raw_path: str, *, allow_root: bool = False
) -> tuple[Path, str] | web.Response:
    """Resolve a raw path inside the workspace with traversal protection.

    Returns ``(resolved_path, clean_relative)`` on success, or a ``web.Response``
    with an appropriate error status on failure.

    If *allow_root* is True, an empty or ``/`` raw_path resolves to the workspace
    root itself.
    """
    if not raw_path:
        if allow_root:
            return workspace_path, ""
        return web.json_response({"error": "missing path"}, status=422)

    # Strip leading /
    clean = raw_path.lstrip("/") if raw_path != "/" else ""

    if raw_path == "/":
        if allow_root:
            return workspace_path, ""
        return web.json_response({"error": "missing path"}, status=422)

    resolved = (workspace_path / clean).resolve()

    # Path traversal protection
    if not str(resolved).startswith(str(workspace_path) + os.sep) and resolved != workspace_path:
        logger.warning("path traversal blocked: %s -> %s", raw_path, resolved)
        return web.json_response({"error": "invalid path"}, status=400)

    return resolved, clean


# ── Misc helpers ─────────────────────────────────────────────────────────────


def mask_key_display(key: str) -> str:
    """Mask an API key for display, showing only first 4 and last 4 chars."""
    if not key or len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


# ── User workspace helpers ───────────────────────────────────────────────────

_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def get_user_workspace_path(request: web.Request) -> Path | web.Response:
    """返回用户级工作空间路径：{base_workspace}/{username}/

    首次访问时生成 user_config.json 配置文件完成初始化。
    包含路径安全校验（防目录遍历）。
    """
    workspace_dir = request.app.get("workspace_dir", "")
    if not workspace_dir:
        return web.json_response({"error": "workspace_dir not configured"}, status=500)
    base = Path(workspace_dir).resolve()

    user = get_current_user(request)
    if not user:
        return base  # 未认证回退到全局

    username = user["username"]
    if not _USERNAME_RE.match(username):
        return web.json_response({"error": "invalid username"}, status=400)

    # 防 symlink 攻击：在 resolve() 之前检查
    candidate = base / username
    if candidate.is_symlink():
        return web.json_response({"error": "invalid path"}, status=400)

    user_ws = candidate.resolve()
    # 防目录遍历
    if not str(user_ws).startswith(str(base) + "/"):
        return web.json_response({"error": "invalid path"}, status=400)

    # 懒创建：首次访问时从模板初始化
    if not user_ws.exists():
        user_ws.mkdir(parents=True, exist_ok=True)
        _init_user_workspace(user_ws, workspace_base=base)

    return user_ws


def generate_user_init_json() -> dict:
    """生成用户初始化配置 JSON 结构，与 workspace-init/ 目录中的 md 文件语义一致。"""
    return {
        "agent": {
            "onboarding_sop": {
                "steps": [
                    {"id": 1, "key": "naming", "label": "起名", "done": False},
                    {"id": 2, "key": "primary_use", "label": "主要用途", "done": False},
                    {"id": 3, "key": "reply_style", "label": "回复风格", "done": False},
                    {"id": 4, "key": "user_info", "label": "用户信息", "done": False},
                    {"id": 5, "key": "taboos", "label": "禁忌", "done": False},
                    {"id": 6, "key": "sop_training", "label": "SOP 调教", "done": False},
                ]
            },
            "skills": [
                {"name": "pdf", "type": "task", "trigger": "用户上传 PDF 文件，需要解析内容"},
                {"name": "docx", "type": "task", "trigger": "用户上传 Word 文档"},
                {"name": "pptx", "type": "task", "trigger": "用户上传 PPT 文件"},
                {"name": "xlsx", "type": "task", "trigger": "用户上传 Excel 表格"},
                {"name": "feishu_ops", "type": "task", "trigger": "需要读取飞书文档、向他人发消息"},
                {"name": "scheduler_mgr", "type": "task", "trigger": "创建/管理定时任务"},
                {"name": "baidu_search", "type": "task", "trigger": "搜索网络最新信息"},
                {"name": "web_browse", "type": "task", "trigger": "访问具体网页获取内容"},
                {"name": "history_reader", "type": "reference", "trigger": "查询历史对话记录"},
                {"name": "memory-save", "type": "task", "trigger": "将用户偏好/事实/规范持久化到 workspace 文件"},
                {"name": "skill-creator", "type": "task", "trigger": "将 SOP 固化为可复用的 SKILL.md"},
                {"name": "memory-governance", "type": "task", "trigger": "审计并清理 workspace 记忆文件"},
                {"name": "search_memory", "type": "task", "trigger": "语义搜索历史对话记忆"},
            ],
            "memory_rules": {
                "auto_save_triggers": [
                    "用户表达偏好、习惯或禁忌",
                    "用户确认了某个工作方式或回复风格",
                    "用户提供了重要背景信息",
                ],
                "target_mapping": {
                    "user_preference": "user",
                    "workflow_sop": "agent",
                    "topic_event": "topic",
                },
            },
            "tool_principles": [
                "先判断是否真的需要工具，简单回答不要调用",
                "优先用最轻量的工具完成任务",
                "工具失败时提供人工替代方案，不要重复无效重试",
            ],
            "capability_boundary": {
                "cannot": ["直接访问本地文件系统（需通过 Sandbox）", "发送邮件（无邮件工具）"],
                "can": ["通过飞书 API 操作飞书内容", "执行 Python/Node.js 代码（在 Sandbox 中隔离执行）"],
            },
        },
        "soul": {
            "name": "xuanji",
            "identity": "本地工作助手，通过飞书与用户沟通，帮助用户完成日常工作任务",
            "personality": ["简洁直接", "主动积极", "诚实可靠", "有记忆"],
            "work_principles": [
                "优先使用工具完成任务，而不是仅仅给出建议",
                "遇到权限或能力边界时，清楚说明限制并提供替代方案",
                "处理敏感信息时不在对话中明文展示",
            ],
            "reply_style": {
                "format": "飞书 Markdown",
                "language": "中文为主，代码注释和技术术语可保留英文",
                "length": "控制在合理长度，避免刷屏",
            },
        },
        "user": {
            "greeting": "",
            "timezone": "Asia/Shanghai",
            "language": "中文",
            "role": "",
            "primary_work": "",
            "common_tools": [],
            "reply_length_preference": "简洁",
            "code_language_preference": "",
            "special_notes": "",
            "important_memories": [],
        },
        "memory": {
            "user_important_items": [],
            "pending_follow_ups": [],
            "recent_session_summaries": [],
        },
    }


def _init_user_workspace(user_ws: Path, workspace_base: Path) -> None:
    """Initialize the user workspace with default files.

    Args:
        user_ws: The user's workspace directory.
        workspace_base: The global workspace base directory (for copying SKILL.md etc.).
    """
    _ensure_dirs(user_ws)

    # Copy user_config.json from global workspace if not exists
    config_src = workspace_base / "user_config.json"
    config_dst = user_ws / "user_config.json"
    if not config_dst.exists() and config_src.exists():
        shutil.copy2(config_src, config_dst)

    # Copy all markdown files
    _copy_md_files(user_ws, workspace_base)

    # Copy SKILL.md directory (skills/)
    _copy_tree_if_exists(workspace_base / "skills", user_ws / "skills")

    # Copy AGENTS.md directory (agents/)
    _copy_tree_if_exists(workspace_base / "agents", user_ws / "agents")


def _copy_md_files(user_ws: Path, workspace_base: Path) -> None:
    """Copy markdown files from global workspace to user workspace."""
    md_files = ["soul.md", "agent.md", "user.md", "memory.md"]
    for md_file in md_files:
        src = workspace_base / md_file
        dst = user_ws / md_file
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)


def _copy_tree_if_exists(src: Path, dst: Path) -> None:
    """Copy a directory tree if the source exists."""
    if src.exists() and src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def _ensure_dirs(user_ws: Path) -> None:
    """Ensure necessary subdirectories exist in the user workspace."""
    (user_ws / "skills").mkdir(parents=True, exist_ok=True)
    (user_ws / "agents").mkdir(parents=True, exist_ok=True)

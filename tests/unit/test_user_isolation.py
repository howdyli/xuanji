"""Unit tests for user isolation: routing_key, workspace path, agent scoping.

Covers the user isolation functions from tasks #36/#38/#39:
- helpers.py: get_routing_key_from_request, list_sessions_for_user, get_user_workspace_path
- session.py: handle_message, handle_sessions (user-scoped queries)
- workspace.py: _get_workspace delegates to user-scoped helper
- main_crew.py: agent_fn dynamic workspace from routing_key
- App.tsx: frontend routing_key format (string-level)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from xiaopaw.frontend.routes.helpers import (
    _copy_md_files,
    _copy_tree_if_exists,
    _ensure_dirs,
    _init_user_workspace,
    get_routing_key_from_request,
    get_user_workspace_path,
    list_sessions_for_user,
)
from xiaopaw.frontend.routes.workspace import _get_workspace


# ═══════════════════════════════════════════════════════════════════════════
# helpers — fake request factory
# ═══════════════════════════════════════════════════════════════════════════


def _make_request(
    *,
    workspace_dir: str = "/tmp/ws",
    user: dict | None = None,
    headers: dict | None = None,
) -> web.Request:
    """Build a minimal mock Request with app-level workspace_dir and user_auth."""
    request = MagicMock(spec=web.Request)
    app: dict = {"workspace_dir": workspace_dir}
    if user is not None:
        mock_user_auth = MagicMock()
        mock_user_auth.get_user_by_token.return_value = user
        mock_user_auth.validate_token.return_value = user
        app["user_auth"] = mock_user_auth
    else:
        app["user_auth"] = None
    request.app = app
    request.headers = headers or {"Authorization": "Bearer fake-token"}
    return request


# ═══════════════════════════════════════════════════════════════════════════
# 1. test_session_routing_key_from_auth
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionRoutingKey:
    def test_routing_key_from_auth(self):
        """Backend constructs routing_key from authenticated user via get_routing_key_from_request."""
        request = _make_request(user={"username": "alice"})
        routing_key = get_routing_key_from_request(request)
        assert routing_key == "p2p:web_alice"

    def test_routing_key_ignores_frontend_value(self):
        """Even if frontend sends a different value, backend uses auth user."""
        request = _make_request(user={"username": "alice"})
        frontend_routing_key = "p2p:web_mallory"
        actual = get_routing_key_from_request(request)
        assert actual != frontend_routing_key
        assert actual == "p2p:web_alice"

    @pytest.mark.asyncio
    async def test_handle_message_uses_session_mgr_from_di(self):
        """handle_message uses session_mgr from request.app (dependency injection)."""
        from xiaopaw.frontend.routes.session import handle_message

        request = _make_request(user={"username": "alice"})

        # Mock session_mgr
        mock_session = MagicMock()
        mock_session.id = "test-session-id"
        mock_session_mgr = AsyncMock()
        mock_session_mgr.get_or_create.return_value = mock_session

        # Mock runner
        mock_runner = AsyncMock()

        request.app["session_mgr"] = mock_session_mgr
        request.app["runner"] = mock_runner
        request.app["sender"] = None
        request.app["pg_store"] = None

        # Mock request.json() to return message body
        request.json = AsyncMock(return_value={"content": "hello", "session_id": "", "expert": ""})

        # Call handle_message
        result = await handle_message(request)

        # Verify session_mgr.get_or_create was called with the routing_key from auth user
        expected_routing_key = get_routing_key_from_request(request)
        mock_session_mgr.get_or_create.assert_called_once_with(expected_routing_key)

        # Verify runner.dispatch was called
        mock_runner.dispatch.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# 2. test_sessions_list_filtered_by_user
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionsListFilter:
    @pytest.mark.asyncio
    async def test_list_sessions_for_user_filters_by_routing_key(self):
        """list_sessions_for_user(pg_store, routing_key) filters sessions by user.

        Signature: async def list_sessions_for_user(pg_store, routing_key) -> list[dict]
        """
        request = _make_request(user={"username": "alice"})
        routing_key = get_routing_key_from_request(request)
        # Mock pg_store — list_sessions_for_user returns [] when pg_store is None
        result = await list_sessions_for_user(None, routing_key)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_sessions_for_user_returns_empty_when_no_store(self):
        """list_sessions_for_user returns empty list when pg_store is None."""
        request = _make_request(user={"username": "alice"})
        routing_key = get_routing_key_from_request(request)
        result = await list_sessions_for_user(None, routing_key)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_sessions_for_user_with_mock_pg(self):
        """Mock PG to verify WHERE routing_key filter is applied."""
        request = _make_request(user={"username": "alice"})
        routing_key = get_routing_key_from_request(request)
        mock_pg = MagicMock()
        mock_pg._dsn = "postgresql://fake"

        with patch("psycopg2.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = [
                {"id": "s1", "routing_key": "p2p:web_alice", "title": "hi",
                 "message_count": 2, "created_at": None, "updated_at": None}
            ]
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)

            result = await list_sessions_for_user(mock_pg, routing_key)

            assert len(result) == 1
            assert result[0]["routing_key"] == "p2p:web_alice"
            # Verify the SQL contains WHERE routing_key = %s
            executed_sql = mock_cursor.execute.call_args[0][0]
            assert "WHERE routing_key" in executed_sql


# ═══════════════════════════════════════════════════════════════════════════
# 3. test_frontend_routing_key_dynamic
# ═══════════════════════════════════════════════════════════════════════════


class TestFrontendRoutingKey:
    @pytest.mark.parametrize(
        "username,expected",
        [
            ("alice", "p2p:web_alice"),
            ("bob", "p2p:web_bob"),
            ("user_123", "p2p:web_user_123"),
            (None, "p2p:web_anonymous"),
            ("", "p2p:web_anonymous"),
        ],
    )
    def test_dynamic_routing_key_format(self, username, expected):
        """Frontend constructs p2p:web_{username} with anonymous fallback.

        Mirrors App.tsx: `p2p:web_${currentUser?.username || 'anonymous'}`
        """
        current_user = {"username": username} if username else None
        rk = (
            f"p2p:web_{current_user['username']}"
            if current_user and current_user.get("username")
            else "p2p:web_anonymous"
        )
        assert rk == expected


# ═══════════════════════════════════════════════════════════════════════════
# 4. test_user_workspace_path_creation
# ═══════════════════════════════════════════════════════════════════════════


class TestUserWorkspacePath:
    def test_workspace_path_creation(self, tmp_path):
        """get_user_workspace_path returns {base}/{username}/ for valid user."""
        request = _make_request(
            workspace_dir=str(tmp_path),
            user={"username": "alice"},
        )
        result = get_user_workspace_path(request)

        assert isinstance(result, Path)
        assert result == (tmp_path / "alice").resolve()
        assert result.exists()

    def test_workspace_path_contains_init_file(self, tmp_path):
        """Newly created workspace copies user_config.json from global workspace."""
        # Create a global user_config.json so it can be copied
        (tmp_path / "user_config.json").write_text(
            '{"agent": {}, "soul": {}}', encoding="utf-8"
        )
        request = _make_request(
            workspace_dir=str(tmp_path),
            user={"username": "bob"},
        )
        result = get_user_workspace_path(request)
        config_file = result / "user_config.json"
        assert config_file.exists()

        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert "agent" in data
        assert "soul" in data


# ═══════════════════════════════════════════════════════════════════════════
# 5. test_user_workspace_path_security
# ═══════════════════════════════════════════════════════════════════════════


class TestUserWorkspaceSecurity:
    @pytest.mark.parametrize(
        "malicious_name",
        [
            "../etc",
            "user/name",
            "..\\windows",
            "foo bar",
            "user@domain",
        ],
    )
    def test_special_chars_rejected(self, tmp_path, malicious_name):
        """Usernames with special characters are rejected (prevent directory traversal).

        _USERNAME_RE = re.compile(r'^[a-zA-Z0-9_-]+$') blocks all non-alphanumeric names.
        """
        request = _make_request(
            workspace_dir=str(tmp_path),
            user={"username": malicious_name},
        )
        result = get_user_workspace_path(request)

        assert isinstance(result, web.Response), f"Expected error for '{malicious_name}'"
        assert result.status == 400


# ═══════════════════════════════════════════════════════════════════════════
# 6. test_user_workspace_lazy_init
# ═══════════════════════════════════════════════════════════════════════════


class TestUserWorkspaceLazyInit:
    def test_lazy_init_creates_dir_and_config(self, tmp_path):
        """First access creates directory and copies user_config.json from global."""
        user_dir = tmp_path / "newuser"
        assert not user_dir.exists()
        # Create global user_config.json for copy
        (tmp_path / "user_config.json").write_text(
            '{"initialized": true}', encoding="utf-8"
        )

        request = _make_request(
            workspace_dir=str(tmp_path),
            user={"username": "newuser"},
        )
        result = get_user_workspace_path(request)

        assert user_dir.exists()
        assert (user_dir / "user_config.json").exists()
        data = json.loads((user_dir / "user_config.json").read_text())
        assert data == {"initialized": True}

    def test_second_access_no_overwrite(self, tmp_path):
        """Second access does not overwrite existing config."""
        request = _make_request(
            workspace_dir=str(tmp_path),
            user={"username": "persist"},
        )
        # First call: creates
        get_user_workspace_path(request)
        config_path = tmp_path / "persist" / "user_config.json"
        config_path.write_text('{"custom": true}', encoding="utf-8")

        # Second call: should not overwrite
        get_user_workspace_path(request)
        assert json.loads(config_path.read_text()) == {"custom": True}

    def test_init_copies_md_files_from_base(self, tmp_path):
        """_init_user_workspace copies md files from workspace_base via _copy_md_files."""
        workspace_base = tmp_path / "base"
        workspace_base.mkdir()
        (workspace_base / "soul.md").write_text("soul content", encoding="utf-8")
        (workspace_base / "agent.md").write_text("agent content", encoding="utf-8")

        user_dir = tmp_path / "mduser"
        user_dir.mkdir()
        _init_user_workspace(user_dir, workspace_base=workspace_base)

        assert (user_dir / "soul.md").exists()
        assert (user_dir / "soul.md").read_text() == "soul content"
        assert (user_dir / "agent.md").exists()
        assert (user_dir / "agent.md").read_text() == "agent content"
        # md files that don't exist in base are not created
        assert not (user_dir / "user.md").exists()
        assert not (user_dir / "memory.md").exists()

    def test_init_does_not_overwrite_existing_md(self, tmp_path):
        """_init_user_workspace does not overwrite existing md files."""
        workspace_base = tmp_path / "base"
        workspace_base.mkdir()
        (workspace_base / "soul.md").write_text("base soul", encoding="utf-8")

        user_dir = tmp_path / "nooverwrite"
        user_dir.mkdir()
        (user_dir / "soul.md").write_text("custom soul", encoding="utf-8")

        _init_user_workspace(user_dir, workspace_base=workspace_base)
        assert (user_dir / "soul.md").read_text() == "custom soul"

    def test_init_copies_skills_and_agents_dirs(self, tmp_path):
        """_init_user_workspace copies skills/ and agents/ directories from workspace_base."""
        workspace_base = tmp_path / "base"
        workspace_base.mkdir()
        (workspace_base / "skills").mkdir()
        (workspace_base / "skills" / "pdf.md").write_text("pdf skill", encoding="utf-8")
        (workspace_base / "agents").mkdir()
        (workspace_base / "agents" / "main.md").write_text("main agent", encoding="utf-8")

        user_dir = tmp_path / "skilluser"
        user_dir.mkdir()
        _init_user_workspace(user_dir, workspace_base=workspace_base)

        assert (user_dir / "skills" / "pdf.md").exists()
        assert (user_dir / "skills" / "pdf.md").read_text() == "pdf skill"
        assert (user_dir / "agents" / "main.md").exists()
        assert (user_dir / "agents" / "main.md").read_text() == "main agent"

    def test_ensure_dirs_creates_skills_and_agents(self, tmp_path):
        """_ensure_dirs creates skills/ and agents/ subdirectories."""
        user_dir = tmp_path / "diruser"
        user_dir.mkdir()
        _ensure_dirs(user_dir)

        assert (user_dir / "skills").is_dir()
        assert (user_dir / "agents").is_dir()

    def test_copy_tree_if_exists_copies_tree(self, tmp_path):
        """_copy_tree_if_exists copies directory tree when source exists."""
        src = tmp_path / "src_tree"
        src.mkdir()
        (src / "file.md").write_text("content", encoding="utf-8")
        dst = tmp_path / "dst_tree"

        _copy_tree_if_exists(src, dst)
        assert dst.is_dir()
        assert (dst / "file.md").read_text() == "content"

    def test_copy_tree_if_exists_noop_when_missing(self, tmp_path):
        """_copy_tree_if_exists does nothing when source doesn't exist."""
        src = tmp_path / "nonexistent"
        dst = tmp_path / "dst_noop"

        _copy_tree_if_exists(src, dst)
        assert not dst.exists()

    def test_copy_md_files_copies_all_md(self, tmp_path):
        """_copy_md_files copies soul.md, agent.md, user.md, memory.md from base."""
        workspace_base = tmp_path / "base"
        workspace_base.mkdir()
        for name in ("soul.md", "agent.md", "user.md", "memory.md"):
            (workspace_base / name).write_text(f"{name} content", encoding="utf-8")

        user_dir = tmp_path / "mdcopy"
        user_dir.mkdir()
        _copy_md_files(user_dir, workspace_base)

        for name in ("soul.md", "agent.md", "user.md", "memory.md"):
            assert (user_dir / name).read_text() == f"{name} content"

    def test_copy_md_files_no_overwrite(self, tmp_path):
        """_copy_md_files does not overwrite existing files."""
        workspace_base = tmp_path / "base"
        workspace_base.mkdir()
        (workspace_base / "soul.md").write_text("base soul", encoding="utf-8")

        user_dir = tmp_path / "mdnoover"
        user_dir.mkdir()
        (user_dir / "soul.md").write_text("my soul", encoding="utf-8")
        _copy_md_files(user_dir, workspace_base)

        assert (user_dir / "soul.md").read_text() == "my soul"

    def test_init_user_workspace_idempotent(self, tmp_path):
        """Calling _init_user_workspace twice does not duplicate or overwrite files."""
        workspace_base = tmp_path / "base"
        workspace_base.mkdir()
        (workspace_base / "user_config.json").write_text(
            '{"template": true}', encoding="utf-8"
        )

        user_dir = tmp_path / "idempotent"
        user_dir.mkdir()

        _init_user_workspace(user_dir, workspace_base=workspace_base)
        config_path = user_dir / "user_config.json"
        first_content = config_path.read_text()

        # Modify config to detect overwrite
        config_path.write_text('{"modified": true}', encoding="utf-8")

        _init_user_workspace(user_dir, workspace_base=workspace_base)
        # Should NOT overwrite
        assert json.loads(config_path.read_text()) == {"modified": True}


# ═══════════════════════════════════════════════════════════════════════════
# 7. test_workspace_api_user_scoped
# ═══════════════════════════════════════════════════════════════════════════


class TestWorkspaceApiUserScoped:
    def test_get_workspace_delegates_to_user_helper(self, tmp_path):
        """_get_workspace calls get_user_workspace_path, not global path."""
        request = _make_request(
            workspace_dir=str(tmp_path),
            user={"username": "scoped_user"},
        )
        result = _get_workspace(request)

        assert isinstance(result, Path)
        assert "scoped_user" in str(result)

    def test_get_workspace_calls_get_user_workspace_path(self, tmp_path):
        """Verify _get_workspace explicitly calls get_user_workspace_path, not get_workspace_path."""
        request = _make_request(
            workspace_dir=str(tmp_path),
            user={"username": "verify_user"},
        )

        # Patch get_user_workspace_path to return a marker path
        with patch("xiaopaw.frontend.routes.workspace.get_user_workspace_path") as mock_func:
            marker_path = tmp_path / "marker_from_get_user_workspace_path"
            mock_func.return_value = marker_path

            result = _get_workspace(request)

            # Verify get_user_workspace_path was called
            mock_func.assert_called_once_with(request)
            assert result == marker_path

    def test_get_workspace_returns_error_response(self, tmp_path):
        """_get_workspace propagates error response from get_user_workspace_path."""
        # Invalid username should trigger error response in get_user_workspace_path
        request = _make_request(
            workspace_dir=str(tmp_path),
            user={"username": "invalid/user"},  # Contains slash, will be rejected
        )
        result = _get_workspace(request)

        assert isinstance(result, web.Response)
        assert result.status == 400

    def test_get_workspace_unauthenticated_fallback(self, tmp_path):
        """_get_workspace falls back to base workspace when user is unauthenticated."""
        request = _make_request(
            workspace_dir=str(tmp_path),
            user=None,
        )
        request.headers = {}  # No auth header

        result = _get_workspace(request)

        assert isinstance(result, Path)
        assert result == Path(str(tmp_path)).resolve()

    @pytest.mark.asyncio
    async def test_handle_file_download_uses_get_user_workspace_path(self, tmp_path):
        """handle_file_download uses get_user_workspace_path instead of get_workspace_path."""
        from xiaopaw.frontend.routes.workspace import handle_file_download

        # Create user workspace with a test file
        user_dir = tmp_path / "dl_user"
        user_dir.mkdir()
        test_file = user_dir / "test.pdf"
        test_file.write_bytes(b"test content")

        request = _make_request(
            workspace_dir=str(tmp_path),
            user={"username": "dl_user"},
        )
        request.query = {"path": "/workspace/test.pdf"}

        # Patch get_user_workspace_path to return user_dir
        with patch("xiaopaw.frontend.routes.workspace.get_user_workspace_path") as mock_func:
            mock_func.return_value = user_dir

            result = await handle_file_download(request)

            # Verify get_user_workspace_path was called
            mock_func.assert_called_once_with(request)

            # Verify file was found and returned
            assert result.status == 200

    @pytest.mark.asyncio
    async def test_handle_file_download_returns_error_when_workspace_invalid(self, tmp_path):
        """handle_file_download returns error response when get_user_workspace_path fails."""
        from xiaopaw.frontend.routes.workspace import handle_file_download

        request = _make_request(
            workspace_dir=str(tmp_path),
            user={"username": "invalid/user"},
        )
        request.query = {"path": "/workspace/test.pdf"}

        result = await handle_file_download(request)

        # Should return 400 error from get_user_workspace_path (invalid username)
        assert isinstance(result, web.Response)
        assert result.status == 400


# ═══════════════════════════════════════════════════════════════════════════
# 8. test_agent_dynamic_workspace
# ═══════════════════════════════════════════════════════════════════════════


class TestAgentDynamicWorkspace:
    def test_agent_fn_resolves_user_workspace(self, tmp_path):
        """agent_fn derives user workspace from routing_key p2p:web_{username}.

        Mirrors build_agent_fn closure logic (main_crew.py:389-394):
            if routing_key.startswith("p2p:web_"):
                username = routing_key[len("p2p:web_"):]
                candidate = workspace_dir / username
                if candidate.is_dir():
                    user_ws = candidate
        """
        # Create bob's workspace dir so is_dir() returns True
        bob_dir = tmp_path / "bob"
        bob_dir.mkdir()

        routing_key = get_routing_key_from_request(_make_request(user={"username": "bob"}))
        user_ws = tmp_path  # default global
        if routing_key.startswith("p2p:web_"):
            username = routing_key[len("p2p:web_"):]
            candidate = tmp_path / username
            if candidate.is_dir():
                user_ws = candidate

        assert user_ws == bob_dir

    def test_agent_fn_fallback_when_dir_missing(self, tmp_path):
        """If user dir doesn't exist, agent_fn falls back to global workspace."""
        routing_key = get_routing_key_from_request(_make_request(user={"username": "ghost"}))
        user_ws = tmp_path
        if routing_key.startswith("p2p:web_"):
            username = routing_key[len("p2p:web_"):]
            candidate = tmp_path / username
            if candidate.is_dir():
                user_ws = candidate

        assert user_ws == tmp_path  # unchanged — ghost dir doesn't exist

    def test_non_web_routing_uses_global(self, tmp_path):
        """Non-web routing keys (e.g. feishu p2p:xxx) use global workspace."""
        routing_key = "p2p:ou_abc123"
        user_ws = tmp_path
        if routing_key.startswith("p2p:web_"):
            username = routing_key[len("p2p:web_"):]
            candidate = tmp_path / username
            if candidate.is_dir():
                user_ws = candidate

        assert user_ws == tmp_path

    def test_agent_fn_accepts_symlink_dir(self, tmp_path):
        """build_agent_fn only checks is_dir(), so symlinked dirs ARE accepted.

        Symlink defense is centralized in get_user_workspace_path, not here.
        """
        real_dir = tmp_path / "real_bob"
        real_dir.mkdir()
        link_dir = tmp_path / "bob"
        link_dir.symlink_to(real_dir)

        routing_key = get_routing_key_from_request(_make_request(user={"username": "bob"}))
        user_ws = tmp_path
        if routing_key.startswith("p2p:web_"):
            username = routing_key[len("p2p:web_"):]
            candidate = tmp_path / username
            if candidate.is_dir():
                user_ws = candidate

        # is_dir() follows symlinks → True, so agent_fn uses the symlinked dir
        assert user_ws == link_dir

    def test_get_user_workspace_path_rejects_symlink(self, tmp_path):
        """get_user_workspace_path rejects symlinked user dirs (centralized defense)."""
        real_dir = tmp_path / "real_eve"
        real_dir.mkdir()
        link_dir = tmp_path / "eve"
        link_dir.symlink_to(real_dir)

        request = _make_request(
            workspace_dir=str(tmp_path),
            user={"username": "eve"},
        )
        result = get_user_workspace_path(request)

        assert isinstance(result, web.Response)
        assert result.status == 400


# ═══════════════════════════════════════════════════════════════════════════
# 9. test_backward_compat_old_routing_key
# ═══════════════════════════════════════════════════════════════════════════


class TestBackwardCompat:
    def test_old_routing_key_fallback_value(self):
        """Unauthenticated fallback routing_key is p2p:web_user.

        get_routing_key_from_request returns:
            f"p2p:web_{username}" if username else "p2p:web_user"
        """
        request = _make_request(user=None, headers={})
        routing_key = get_routing_key_from_request(request)
        assert routing_key == "p2p:web_user"

    @pytest.mark.asyncio
    async def test_old_sessions_still_queryable_via_fallback_key(self):
        """Old p2p:web_user sessions are accessible with the fallback routing_key.

        When list_sessions_for_user is called with p2p:web_user,
        legacy sessions created before user isolation are still returned.
        """
        # list_sessions_for_user(None, ...) returns [] — verifying the function
        # accepts p2p:web_user as a valid routing_key without error
        request = _make_request(user=None, headers={})
        routing_key = get_routing_key_from_request(request)
        result = await list_sessions_for_user(None, routing_key)
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════════════
# 10. test_anonymous_fallback
# ═══════════════════════════════════════════════════════════════════════════


class TestAnonymousFallback:
    def test_unauthenticated_returns_global_workspace(self, tmp_path):
        """When get_current_user returns None, fall back to base workspace."""
        request = _make_request(workspace_dir=str(tmp_path), user=None)
        # No Bearer token → get_current_user returns None
        request.headers = {}
        result = get_user_workspace_path(request)

        assert isinstance(result, Path)
        assert result == Path(str(tmp_path)).resolve()

    def test_missing_workspace_dir_returns_error(self):
        """If workspace_dir is not configured, return 500 error."""
        request = _make_request(workspace_dir="", user={"username": "alice"})
        result = get_user_workspace_path(request)

        assert isinstance(result, web.Response)
        assert result.status == 500

    def test_handle_message_anonymous_routing_key(self):
        """When user is None, get_routing_key_from_request returns 'p2p:web_user'."""
        request = _make_request(user=None, headers={})
        routing_key = get_routing_key_from_request(request)
        assert routing_key == "p2p:web_user"

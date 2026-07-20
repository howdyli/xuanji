"""Integration tests for skill moderation.

Covers three areas:
1. UserAuth is_admin migration + defaults + set_admin (pure SQLite, always run).
2. Community review flow: publish -> list_pending -> approve -> visible ->
   reject -> hidden + review_note (requires PostgreSQL; skipped otherwise).
3. Local install closure: an approved ``local://`` skill installs successfully.
4. Permission: non-admin callers get 403 on the admin endpoints.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from xiaopaw.frontend.auth import UserAuth
from xiaopaw.skills_mgmt.api import register_community_routes
from xiaopaw.skills_mgmt.community import CommunityError, CommunityRegistry
from xiaopaw.skills_mgmt.packager import pack_skill


# ─── UserAuth is_admin (pure SQLite, no PG required) ─────────────────────────


@pytest.fixture
def auth(tmp_path):
    return UserAuth(tmp_path / "auth.db")


def test_default_admin_is_admin(auth):
    """The bootstrapped default admin account has is_admin=True."""
    admin = auth.get_first_user()
    assert admin["username"] == "admin"
    assert auth.is_admin(admin["id"]) is True
    # get_user carries the is_admin flag as a bool
    full = auth.get_user(admin["id"])
    assert full["is_admin"] is True


def test_registered_user_not_admin(auth):
    """Regular self-service registration yields a non-admin user."""
    _, user = auth.register("alice", "password123")
    assert user["is_admin"] is False
    assert auth.is_admin(user["id"]) is False


def test_set_admin_grants_and_revokes(auth):
    """set_admin toggles the privilege in both directions."""
    _, user = auth.register("bob", "password123")
    assert auth.set_admin(user["id"], True) is True
    assert auth.is_admin(user["id"]) is True
    assert auth.set_admin(user["id"], False) is True
    assert auth.is_admin(user["id"]) is False


def test_migration_adds_is_admin_to_legacy_db(tmp_path):
    """A pre-existing users table without is_admin is migrated idempotently."""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "username TEXT UNIQUE NOT NULL, "
        "password_hash TEXT NOT NULL, "
        "created_at TEXT NOT NULL);"
    )
    conn.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        ("legacy", "x", "2020-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    # Initialising UserAuth on the legacy DB must add the column without error.
    migrated = UserAuth(db)
    cols = {
        row[1]
        for row in sqlite3.connect(str(db)).execute("PRAGMA table_info(users)").fetchall()
    }
    assert "is_admin" in cols
    # Existing user defaults to non-admin.
    user = migrated.get_user(1)
    assert user["is_admin"] is False


# ─── Permission enforcement (real UserAuth + mocked registry, no PG) ─────────


@pytest.fixture
def admin_app(tmp_path):
    """aiohttp app with real UserAuth (admin + alice) and a mocked registry."""
    auth = UserAuth(tmp_path / "auth.db")  # bootstraps default admin
    admin_token, _ = auth.login("admin", "admin123")
    alice_token, _ = auth.register("alice", "password123")

    app = web.Application()
    app["user_auth"] = auth
    reg = MagicMock(spec=CommunityRegistry)
    reg.list_pending.return_value = {"skills": [], "total": 0}
    reg.moderate_skill.return_value = {"name": "x", "status": "approved"}
    register_community_routes(app, reg)
    return app, admin_token, alice_token, reg


@pytest.mark.asyncio
async def test_pending_requires_admin(admin_app):
    """GET /admin/pending: 403 for non-admin, 200 for admin."""
    app, admin_token, alice_token, _ = admin_app
    async with TestClient(TestServer(app)) as client:
        r = await client.get(
            "/api/frontend/market/community/admin/pending",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert r.status == 403

        r2 = await client.get(
            "/api/frontend/market/community/admin/pending",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r2.status == 200


@pytest.mark.asyncio
async def test_moderate_requires_admin(admin_app):
    """POST /admin/skills/{name}/moderate: 403 for non-admin, 200 for admin."""
    app, admin_token, alice_token, reg = admin_app
    async with TestClient(TestServer(app)) as client:
        r = await client.post(
            "/api/frontend/market/community/admin/skills/foo/moderate",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={"action": "approve"},
        )
        assert r.status == 403
        reg.moderate_skill.assert_not_called()

        r2 = await client.post(
            "/api/frontend/market/community/admin/skills/foo/moderate",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "approve"},
        )
        assert r2.status == 200
        reg.moderate_skill.assert_called_once()


@pytest.mark.asyncio
async def test_moderate_unauthenticated(admin_app):
    """No token at all is rejected as forbidden."""
    app, _, _, _ = admin_app
    async with TestClient(TestServer(app)) as client:
        r = await client.get("/api/frontend/market/community/admin/pending")
        assert r.status == 403


# ─── Community review + install closure (requires PostgreSQL) ────────────────


def _get_pg_dsn() -> str | None:
    dsn = os.environ.get("XIAOPAW_TEST_PG_DSN")
    if dsn:
        return dsn
    try:
        from xiaopaw.config.validator import load_config

        cfg = load_config(Path(os.environ.get("XIAOPAW_CONFIG", "config.yaml")))
        return cfg.memory.db_dsn
    except Exception:
        return None


@pytest.fixture
def pg_registry(tmp_path):
    """Real CommunityRegistry against PostgreSQL; skips when unavailable."""
    dsn = _get_pg_dsn()
    if not dsn:
        pytest.skip("no PostgreSQL DSN configured (set XIAOPAW_TEST_PG_DSN)")
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 not installed")
    try:
        conn = psycopg2.connect(dsn)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL unavailable: {exc}")

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.community_skills')")
                if cur.fetchone()[0] is None:
                    pytest.skip("community_skills table missing; apply schema.sql first")
                # Ensure moderation audit columns exist (idempotent).
                cur.execute(
                    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS reviewed_by TEXT"
                )
                cur.execute(
                    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ"
                )
                cur.execute(
                    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS "
                    "review_note TEXT NOT NULL DEFAULT ''"
                )
        publisher = f"pub_{uuid.uuid4().hex[:8]}"
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username) VALUES (%s) ON CONFLICT DO NOTHING",
                    (publisher,),
                )
    finally:
        conn.close()

    user_dir = tmp_path / "user_skills"
    user_dir.mkdir()
    storage = tmp_path / "storage"
    storage.mkdir()
    reg = CommunityRegistry(
        pg_dsn=dsn,
        market_registry=MagicMock(),
        user_dir=user_dir,
        event_bus=MagicMock(),
        storage_dir=storage,
    )
    created: list[str] = []
    yield reg, publisher, created

    # Cleanup published rows + the test publisher.
    try:
        conn = psycopg2.connect(dsn)
        with conn:
            with conn.cursor() as cur:
                for nm in created:
                    cur.execute("DELETE FROM community_skills WHERE name = %s", (nm,))
                cur.execute("DELETE FROM users WHERE username = %s", (publisher,))
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def _make_zip(tmp_path: Path, name: str) -> Path:
    src = tmp_path / "src" / name
    src.mkdir(parents=True, exist_ok=True)
    (src / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test\nversion: 1.0.0\n---\nhello body\n",
        encoding="utf-8",
    )
    zip_path = tmp_path / f"{name}.zip"
    zip_path.write_bytes(pack_skill(src))
    return zip_path


@pytest.mark.asyncio
async def test_publish_moderate_install_flow(pg_registry, tmp_path):
    """Full loop: publish -> pending -> approve -> visible -> install -> reject."""
    reg, publisher, created = pg_registry
    name = f"skill_{uuid.uuid4().hex[:8]}"
    created.append(name)
    zip_path = _make_zip(tmp_path, name)

    row = reg.publish_skill(
        publisher=publisher,
        metadata={"name": name, "description": "d"},
        zip_path=zip_path,
    )
    assert row["status"] == "pending"

    # Appears in the pending queue, absent from the public listing.
    pending = reg.list_pending()
    assert any(s["name"] == name for s in pending["skills"])
    assert all(s["name"] != name for s in reg.list_skills()["skills"])

    # Approve -> audit fields recorded, now publicly listed.
    updated = reg.moderate_skill(name, "approve", reviewer="admin", note="")
    assert updated["status"] == "approved"
    assert updated["reviewed_by"] == "admin"
    assert updated["reviewed_at"] is not None
    assert any(s["name"] == name for s in reg.list_skills()["skills"])

    # Install closure: the local:// archive unpacks into the user dir.
    unpacked = await reg.install_skill(name, user_id="tester")
    assert unpacked == name
    assert (reg._user_dir / name / "SKILL.md").exists()

    # Reject -> hidden again, review_note persisted.
    reg.moderate_skill(name, "reject", reviewer="admin", note="bad quality")
    detail = reg.get_skill(name)
    assert detail["status"] == "rejected"
    assert detail["review_note"] == "bad quality"
    assert all(s["name"] != name for s in reg.list_skills()["skills"])


def test_moderate_invalid_action_and_not_found(pg_registry):
    """moderate_skill raises typed errors for bad action / missing skill."""
    reg, _publisher, _created = pg_registry
    with pytest.raises(CommunityError) as bad_action:
        reg.moderate_skill("whatever", "delete", reviewer="admin")
    assert bad_action.value.code == "invalid_action"

    missing = f"missing_{uuid.uuid4().hex[:8]}"
    with pytest.raises(CommunityError) as not_found:
        reg.moderate_skill(missing, "approve", reviewer="admin")
    assert not_found.value.code == "not_found"

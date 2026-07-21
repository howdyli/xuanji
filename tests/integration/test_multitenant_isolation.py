"""Integration tests for multi-tenant isolation (Spec A foundation).

Covers three areas:
1. Organization bootstrap + backfill + team org inheritance (pure SQLite,
   always run).
2. Session org depth-defense visibility helper (pure, always run).
3. sessions.org_id persistence + startup backfill (requires PostgreSQL;
   skipped otherwise).
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

import pytest

from xiaopaw.frontend.auth import UserAuth
from xiaopaw.frontend.team import TeamStore
from xiaopaw.frontend.routes.session import _org_visible


# ─── Organization bootstrap + backfill (pure SQLite, no PG required) ─────────


@pytest.fixture
def auth(tmp_path):
    return UserAuth(tmp_path / "auth.db")


def test_default_org_bootstrap(auth):
    """A default organization is created and owned by the bootstrapped admin."""
    org_id = auth.get_default_org_id()
    assert org_id is not None
    org = auth.get_org(org_id)
    assert org["name"] == "默认组织"

    admin = auth.get_first_user()
    assert org["owner_id"] == admin["id"]
    # get_user carries org_id, pointing at the default org.
    assert auth.get_user(admin["id"])["org_id"] == org_id


def test_registered_user_joins_default_org(auth):
    """Self-service registration assigns the user to the default org."""
    _, user = auth.register("alice", "password123")
    assert user["org_id"] == auth.get_default_org_id()


def test_create_organization_and_move_user(auth):
    """create_organization + set_user_org relocate a user across tenants."""
    _, alice = auth.register("alice", "password123")
    other = auth.create_organization("Acme", alice["id"])
    assert other["id"] != auth.get_default_org_id()
    assert auth.set_user_org(alice["id"], other["id"]) is True
    assert auth.get_user(alice["id"])["org_id"] == other["id"]


def test_all_username_org_map(auth):
    """all_username_org_map returns {username: org_id} for startup backfill."""
    auth.register("alice", "password123")
    mapping = auth.all_username_org_map()
    default_org = auth.get_default_org_id()
    assert mapping["admin"] == default_org
    assert mapping["alice"] == default_org


def test_legacy_db_migration_backfills_org(tmp_path):
    """A pre-existing users/teams DB without org_id is migrated + backfilled."""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            owner_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        ("legacy", "x:y", "2020-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO teams (name, description, owner_id, created_at) VALUES (?, ?, ?, ?)",
        ("Legacy Team", "", 1, "2020-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    auth = UserAuth(db)  # runs migrations + org bootstrap + backfill
    default_org = auth.get_default_org_id()
    assert default_org is not None
    # Legacy user is the first user -> becomes default org owner + backfilled.
    assert auth.get_user(1)["org_id"] == default_org

    conn = sqlite3.connect(str(db))
    team_org = conn.execute("SELECT org_id FROM teams WHERE id = 1").fetchone()[0]
    conn.close()
    assert team_org == default_org


# ─── Team org inheritance + cross-org rejection (pure SQLite) ────────────────


def test_create_team_inherits_owner_org(tmp_path):
    """A new team inherits its owner's organization."""
    auth = UserAuth(tmp_path / "auth.db")
    _, alice = auth.register("alice", "password123")
    store = TeamStore(tmp_path / "auth.db")

    team = store.create_team("Team A", "", alice["id"])
    assert team["org_id"] == alice["org_id"]
    assert store.get_team_org_id(team["id"]) == alice["org_id"]


def test_add_member_same_org_ok_cross_org_rejected(tmp_path):
    """add_member allows same-org joins and rejects cross-org joins."""
    auth = UserAuth(tmp_path / "auth.db")
    _, alice = auth.register("alice", "password123")
    _, bob = auth.register("bob", "password123")
    store = TeamStore(tmp_path / "auth.db")

    # Same (default) org: allowed.
    team_a = store.create_team("Team A", "", alice["id"])
    store.add_member(team_a["id"], bob["id"])
    assert store.is_member(team_a["id"], bob["id"])

    # Move bob into another org, then have him own a team there.
    other = auth.create_organization("Acme", bob["id"])
    auth.set_user_org(bob["id"], other["id"])
    team_b = store.create_team("Team B", "", bob["id"])
    assert team_b["org_id"] == other["id"]

    # carol stays in the default org -> cannot join bob's other-org team.
    _, carol = auth.register("carol", "password123")
    with pytest.raises(ValueError, match="跨组织"):
        store.add_member(team_b["id"], carol["id"])


def test_accept_invitation_cross_org_rejected(tmp_path):
    """Invitation-based joins are also blocked across organizations."""
    auth = UserAuth(tmp_path / "auth.db")
    _, alice = auth.register("alice", "password123")
    _, bob = auth.register("bob", "password123")
    store = TeamStore(tmp_path / "auth.db")

    team = store.create_team("Team A", "", alice["id"])
    invite = store.create_invitation(team["id"], alice["id"])

    # Move bob to another org before accepting.
    other = auth.create_organization("Acme", bob["id"])
    auth.set_user_org(bob["id"], other["id"])

    with pytest.raises(ValueError, match="跨组织"):
        store.accept_invitation(invite["code"], bob["id"])


# ─── Session org depth-defense (pure, always run) ────────────────────────────


def test_org_visible_matrix():
    """The org-visibility helper enforces equal orgs, tolerating NULLs."""
    assert _org_visible(1, 1) is True
    assert _org_visible(1, 2) is False
    assert _org_visible(None, 2) is True   # legacy session row
    assert _org_visible(1, None) is True   # user pre-backfill
    assert _org_visible(None, None) is True


# ─── sessions.org_id persistence + backfill (requires PostgreSQL) ────────────


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
def pg_store_and_dsn():
    """Real PGStore against PostgreSQL; skips when unavailable."""
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
                cur.execute("SELECT to_regclass('public.sessions')")
                if cur.fetchone()[0] is None:
                    pytest.skip("sessions table missing; apply schema.sql first")
                cur.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS org_id BIGINT")
    finally:
        conn.close()

    from xiaopaw.frontend.store import PGStore

    store = PGStore(dsn=dsn)
    yield store, dsn
    store.close()


def _delete_session(dsn: str, sid: str) -> None:
    import psycopg2

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE id = %s", (sid,))
        conn.commit()


@pytest.mark.asyncio
async def test_save_session_persists_org_id_without_overwrite(pg_store_and_dsn):
    """save_session writes org_id and never overwrites an existing one (COALESCE)."""
    import psycopg2

    store, dsn = pg_store_and_dsn
    sid = f"s-{uuid.uuid4().hex[:12]}"
    rk = f"p2p:web_{uuid.uuid4().hex[:6]}"
    try:
        await store.save_session(sid, rk, title="t", message_count=2, org_id=42)
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT org_id FROM sessions WHERE id = %s", (sid,))
                assert cur.fetchone()[0] == 42

        # An upsert carrying org_id=None must keep the existing 42.
        await store.save_session(sid, rk, title="t", message_count=4, org_id=None)
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT org_id, message_count FROM sessions WHERE id = %s", (sid,)
                )
                row = cur.fetchone()
                assert row[0] == 42
                assert row[1] == 4
    finally:
        _delete_session(dsn, sid)


def test_backfill_session_org_ids_only_fills_nulls(pg_store_and_dsn):
    """backfill_session_org_ids fills NULL org rows and never overwrites."""
    import psycopg2

    store, dsn = pg_store_and_dsn
    sid = f"s-{uuid.uuid4().hex[:12]}"
    rk = f"p2p:web_bf_{uuid.uuid4().hex[:6]}"
    try:
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sessions (id, routing_key) VALUES (%s, %s)", (sid, rk)
                )
            conn.commit()

        updated = store.backfill_session_org_ids({rk: 7})
        assert updated >= 1
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT org_id FROM sessions WHERE id = %s", (sid,))
                assert cur.fetchone()[0] == 7

        # A second backfill with a different org must not overwrite.
        store.backfill_session_org_ids({rk: 99})
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT org_id FROM sessions WHERE id = %s", (sid,))
                assert cur.fetchone()[0] == 7
    finally:
        _delete_session(dsn, sid)

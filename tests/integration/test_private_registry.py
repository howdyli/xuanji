"""Tests for the org-scoped private Skill Registry (P2-4).

Two layers:
1. Pure unit tests for the visibility helpers (``_visibility_where`` /
   ``_skill_visible_to``) — always run, encode the access-control semantics.
2. Integration tests against PostgreSQL (skipped when no DSN) covering the
   end-to-end private-skill flow: private publish auto-approves, is visible and
   installable only within its owning org, and is isolated from other orgs.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from xiaopaw.skills_mgmt.community import (
    CommunityError,
    CommunityRegistry,
    _skill_visible_to,
    _visibility_where,
)
from xiaopaw.skills_mgmt.packager import pack_skill

ORG_A = 9001
ORG_B = 9002


# ─── Pure unit tests: visibility helpers (no PostgreSQL) ─────────────────────


def test_visibility_where_no_org_only_public():
    sql, params = _visibility_where(None)
    assert sql == "visibility = 'public'"
    assert params == []


def test_visibility_where_with_org_includes_own_private():
    sql, params = _visibility_where(ORG_A)
    assert "visibility = 'public'" in sql
    assert "owner_org_id = %s" in sql
    assert params == [ORG_A]


def test_skill_visible_to_public_always_visible():
    public = {"visibility": "public", "owner_org_id": None}
    assert _skill_visible_to(public, None) is True
    assert _skill_visible_to(public, ORG_A) is True


def test_skill_visible_to_private_requires_same_org():
    private = {"visibility": "private", "owner_org_id": ORG_A}
    assert _skill_visible_to(private, ORG_A) is True
    assert _skill_visible_to(private, ORG_B) is False
    # No org context can never see a private skill.
    assert _skill_visible_to(private, None) is False


def test_skill_visible_to_missing_visibility_treated_public():
    # Legacy rows without a visibility value default to public semantics.
    assert _skill_visible_to({"owner_org_id": None}, None) is True


# ─── Integration: private registry flow (requires PostgreSQL) ────────────────


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
                # Ensure private-registry columns exist (idempotent).
                cur.execute(
                    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS "
                    "visibility TEXT NOT NULL DEFAULT 'public'"
                )
                cur.execute(
                    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS owner_org_id BIGINT"
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


def test_private_publish_auto_approves_and_scopes(pg_registry, tmp_path):
    """A private skill auto-approves and is visible only to its owning org."""
    reg, publisher, created = pg_registry
    name = f"priv_{uuid.uuid4().hex[:8]}"
    created.append(name)
    zip_path = _make_zip(tmp_path, name)

    row = reg.publish_skill(
        publisher=publisher,
        metadata={"name": name, "description": "d", "visibility": "private"},
        zip_path=zip_path,
        owner_org_id=ORG_A,
    )
    # Auto-approved within org, tagged private + owning org.
    assert row["status"] == "approved"
    assert row["visibility"] == "private"
    assert row["owner_org_id"] == ORG_A

    # Same org sees it; other org and no-org context do not.
    assert any(s["name"] == name for s in reg.list_skills(viewer_org_id=ORG_A)["skills"])
    assert all(s["name"] != name for s in reg.list_skills(viewer_org_id=ORG_B)["skills"])
    assert all(s["name"] != name for s in reg.list_skills()["skills"])

    # get_skill respects the same scoping.
    assert reg.get_skill(name, viewer_org_id=ORG_A) is not None
    assert reg.get_skill(name, viewer_org_id=ORG_B) is None


def test_private_publish_without_org_rejected(pg_registry, tmp_path):
    """Publishing a private skill without an org is a typed error."""
    reg, publisher, created = pg_registry
    name = f"priv_{uuid.uuid4().hex[:8]}"
    zip_path = _make_zip(tmp_path, name)
    with pytest.raises(CommunityError) as exc:
        reg.publish_skill(
            publisher=publisher,
            metadata={"name": name, "description": "d", "visibility": "private"},
            zip_path=zip_path,
            owner_org_id=None,
        )
    assert exc.value.code == "no_org"


@pytest.mark.asyncio
async def test_private_install_forbidden_cross_org(pg_registry, tmp_path):
    """Installing another org's private skill raises forbidden; same org works."""
    reg, publisher, created = pg_registry
    name = f"priv_{uuid.uuid4().hex[:8]}"
    created.append(name)
    zip_path = _make_zip(tmp_path, name)
    reg.publish_skill(
        publisher=publisher,
        metadata={"name": name, "description": "d", "visibility": "private"},
        zip_path=zip_path,
        owner_org_id=ORG_A,
    )

    with pytest.raises(CommunityError) as exc:
        await reg.install_skill(name, user_id="tester", viewer_org_id=ORG_B)
    assert exc.value.code == "forbidden"

    # Owning org installs the local:// archive successfully.
    unpacked = await reg.install_skill(name, user_id="tester", viewer_org_id=ORG_A)
    assert unpacked == name
    assert (reg._user_dir / name / "SKILL.md").exists()

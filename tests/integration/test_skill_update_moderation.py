"""PG-gated integration tests for skill version-update moderation.

Covers the staged re-review loop for install-artifact changes to an approved
skill. Requires PostgreSQL; skipped when unavailable (set XIAOPAW_TEST_PG_DSN).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from xiaopaw.skills_mgmt.community import CommunityRegistry
from xiaopaw.skills_mgmt.packager import pack_skill


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


_PENDING_COLS = (
    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_version TEXT",
    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_install_url TEXT",
    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_archive_hash TEXT",
    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS has_pending_update "
    "BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_submitted_at TIMESTAMPTZ",
    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS reviewed_by TEXT",
    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ",
    "ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS review_note TEXT NOT NULL DEFAULT ''",
)


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
                for stmt in _PENDING_COLS:
                    cur.execute(stmt)
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


def _publish_and_approve(reg, publisher, created, tmp_path, name):
    created.append(name)
    reg.publish_skill(
        publisher=publisher,
        metadata={"name": name, "description": "d", "version": "1.0.0"},
        zip_path=_make_zip(tmp_path, name),
    )
    reg.moderate_skill(name, "approve", reviewer="admin", note="")


def test_artifact_update_stages_and_approve_promotes(pg_registry, tmp_path):
    """Artifact update on an approved skill is staged, then promoted on approve."""
    reg, publisher, created = pg_registry
    name = f"skill_{uuid.uuid4().hex[:8]}"
    _publish_and_approve(reg, publisher, created, tmp_path, name)

    live = reg.get_skill(name)
    old_url = live["install_url"]

    # Stage an artifact update: live stays on the approved version.
    reg.update_skill(name, publisher, {
        "version": "2.0.0",
        "install_url": "local://new",
        "archive_hash": "deadbeef",
    })
    staged = reg.get_skill(name)
    assert staged["version"] == "1.0.0"
    assert staged["install_url"] == old_url
    assert staged["has_pending_update"] is True
    assert staged["status"] == "approved"
    assert any(s["name"] == name for s in reg.list_pending()["skills"])

    # Approve the update: live switches to the new artifact, pending cleared.
    reg.moderate_skill(name, "approve", reviewer="admin", note="ok")
    promoted = reg.get_skill(name)
    assert promoted["version"] == "2.0.0"
    assert promoted["install_url"] == "local://new"
    assert promoted["archive_hash"] == "deadbeef"
    assert promoted["has_pending_update"] is False
    assert all(s["name"] != name for s in reg.list_pending()["skills"])


def test_reject_update_keeps_previous_version(pg_registry, tmp_path):
    """Rejecting an artifact update discards it but keeps the live version."""
    reg, publisher, created = pg_registry
    name = f"skill_{uuid.uuid4().hex[:8]}"
    _publish_and_approve(reg, publisher, created, tmp_path, name)

    reg.update_skill(name, publisher, {"version": "9.9.9", "install_url": "local://bad"})
    reg.moderate_skill(name, "reject", reviewer="admin", note="unsafe payload")

    kept = reg.get_skill(name)
    assert kept["version"] == "1.0.0"
    assert kept["has_pending_update"] is False
    assert kept["status"] == "approved"  # still serving the approved build
    assert kept["review_note"] == "unsafe payload"
    assert all(s["name"] != name for s in reg.list_pending()["skills"])


def test_display_update_applies_immediately(pg_registry, tmp_path):
    """Display-only field changes bypass re-review and take effect at once."""
    reg, publisher, created = pg_registry
    name = f"skill_{uuid.uuid4().hex[:8]}"
    _publish_and_approve(reg, publisher, created, tmp_path, name)

    reg.update_skill(name, publisher, {"description": "brand new copy"})
    row = reg.get_skill(name)
    assert row["description"] == "brand new copy"
    assert row["has_pending_update"] is False
    assert all(s["name"] != name for s in reg.list_pending()["skills"])

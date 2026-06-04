"""Unit tests for ``xiaopaw.skills_mgmt.market``.

Coverage targets (spec §10 V1-V2):
- adapter validation rejects malformed entries (name, scheme, missing URL)
- ``MarketSync`` aggregates multiple sources and isolates per-source errors
- ``to_dict`` exposes the contract used by the frontend
- ``MarketEntry.from_row`` accepts both dict and JSON-string ``manifest_json``
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from xiaopaw.skills_mgmt.market import (
    MarketEntry,
    MarketError,
    MarketRegistry,
    MarketSync,
    _extract_index_items,
    _parse_clawhub_entry,
    _parse_vercel_entry,
)
from xiaopaw.skills_mgmt.packager import pack_skill


# ─── Fakes ───────────────────────────────────────────────────────────────────


class _FakePG:
    """pg_store stub: pretend DB is unavailable so _upsert short-circuits."""

    def _ensure_connection(self) -> bool:  # noqa: D401 (mimic real signature)
        return False


def _make_fetcher(payloads: dict[str, Any]):
    async def _fetch(url: str) -> Any:
        if url not in payloads:
            raise RuntimeError(f"unmocked URL: {url}")
        result = payloads[url]
        if isinstance(result, Exception):
            raise result
        return result

    return _fetch


# ─── _parse_vercel_entry ─────────────────────────────────────────────────────


def test_parse_vercel_entry_minimal_valid():
    item = {
        "name": "ppt-master",
        "version": "1.0.0",
        "description": "PPT skill",
        "author": "vercel",
        "repository": "https://github.com/vercel/skills/tree/main/ppt-master",
        "downloadUrl": "https://example.com/ppt-master.zip",
        "updatedAt": "2024-12-01T10:00:00Z",
    }
    entry = _parse_vercel_entry(item)
    assert entry is not None
    assert entry.name == "ppt-master"
    assert entry.source_type == "vercel"
    assert entry.version == "1.0.0"
    assert entry.install_url == "https://example.com/ppt-master.zip"
    assert entry.repo_url.startswith("https://github.com/")
    assert entry.updated_at == datetime(2024, 12, 1, 10, 0, tzinfo=timezone.utc)
    # raw payload preserved for diagnostic
    assert entry.manifest_json["downloadUrl"] == item["downloadUrl"]


@pytest.mark.parametrize(
    "bad_name",
    ["", "PPT", "with space", "../etc", "name_with_underscore", "1starts-digit"],
)
def test_parse_vercel_entry_rejects_bad_name(bad_name: str):
    item = {"name": bad_name, "downloadUrl": "https://e.com/x.zip"}
    assert _parse_vercel_entry(item) is None


@pytest.mark.parametrize(
    "bad_url",
    ["", "file:///etc/passwd", "ftp://e.com/x.zip", "javascript:alert(1)"],
)
def test_parse_vercel_entry_rejects_non_http_scheme(bad_url: str):
    item = {"name": "ok", "downloadUrl": bad_url}
    assert _parse_vercel_entry(item) is None


def test_parse_vercel_entry_accepts_snake_case_aliases():
    """Backward-compatible field aliases (download_url / repo_url / updated_at)."""
    item = {
        "name": "alias-skill",
        "download_url": "https://e.com/a.zip",
        "repo_url": "https://github.com/a/a",
        "updated_at": "2025-01-15T08:30:00+00:00",
    }
    entry = _parse_vercel_entry(item)
    assert entry is not None
    assert entry.install_url == "https://e.com/a.zip"
    assert entry.repo_url == "https://github.com/a/a"
    assert entry.updated_at is not None


def test_parse_vercel_entry_invalid_iso_keeps_entry():
    """Bad updatedAt ISO should not nuke the entire entry."""
    item = {
        "name": "ok",
        "downloadUrl": "https://e.com/x.zip",
        "updatedAt": "not-a-date",
    }
    entry = _parse_vercel_entry(item)
    assert entry is not None
    assert entry.updated_at is None


def test_parse_vercel_entry_rejects_non_dict():
    assert _parse_vercel_entry("string") is None  # type: ignore[arg-type]
    assert _parse_vercel_entry(None) is None  # type: ignore[arg-type]


# ─── _parse_clawhub_entry ────────────────────────────────────────────────────


def test_parse_clawhub_entry_overrides_source_type():
    item = {"name": "x", "downloadUrl": "https://e.com/x.zip"}
    entry = _parse_clawhub_entry(item)
    assert entry is not None
    assert entry.source_type == "clawhub"


# ─── _extract_index_items ────────────────────────────────────────────────────


def test_extract_index_items_list_passthrough():
    items = [{"a": 1}, {"b": 2}]
    assert _extract_index_items(items) == items


def test_extract_index_items_dict_skills_wrapper():
    payload = {"skills": [{"a": 1}], "version": "v1"}
    assert _extract_index_items(payload) == [{"a": 1}]


def test_extract_index_items_dict_items_wrapper():
    payload = {"items": [{"a": 1}]}
    assert _extract_index_items(payload) == [{"a": 1}]


def test_extract_index_items_filters_non_dict():
    items = [{"ok": True}, "string", 42, None, {"ok": True}]
    out = _extract_index_items(items)
    assert len(out) == 2
    assert all(isinstance(it, dict) for it in out)


def test_extract_index_items_non_iterable_returns_empty():
    assert _extract_index_items(None) == []
    assert _extract_index_items(123) == []


# ─── MarketEntry serialization ───────────────────────────────────────────────


def test_market_entry_to_dict_includes_installed_flag():
    e = MarketEntry(
        name="x",
        source_type="vercel",
        version="1.0.0",
        description="d",
        author="a",
        repo_url="r",
        install_url="https://e.com/x.zip",
    )
    d = e.to_dict(installed=True)
    assert d["name"] == "x"
    assert d["installed"] is True
    assert d["fetched_at"]  # ISO string
    assert d["updated_at"] is None


def test_market_entry_from_row_parses_string_manifest():
    """``manifest_json`` may come back as str (psycopg2 default) or dict."""
    row = {
        "name": "x",
        "source_type": "vercel",
        "version": "1",
        "description": "",
        "author": "",
        "repo_url": "",
        "install_url": "https://e.com/x.zip",
        "manifest_json": '{"foo": 1}',
        "updated_at": None,
        "fetched_at": datetime.now(timezone.utc),
    }
    e = MarketEntry.from_row(row)
    assert e.manifest_json == {"foo": 1}


def test_market_entry_from_row_handles_invalid_json_string():
    row = {
        "name": "x",
        "source_type": "vercel",
        "install_url": "https://e.com/x.zip",
        "manifest_json": "not-json",
        "fetched_at": datetime.now(timezone.utc),
    }
    e = MarketEntry.from_row(row)
    assert e.manifest_json == {}


# ─── MarketSync ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_market_sync_no_sources_configured_short_circuits():
    sync = MarketSync(pg_store=_FakePG(), vercel_index_url="", clawhub_index_url="")
    summary = await sync.sync_to_db()
    assert summary == {"sources": {}, "total_upserted": 0}


@pytest.mark.asyncio
async def test_market_sync_aggregates_two_sources(monkeypatch):
    # MarketSync reads env in __init__; ensure no override leaks into the test.
    monkeypatch.delenv("XIAOPAW_VERCEL_SKILLS_INDEX_URL", raising=False)
    monkeypatch.delenv("XIAOPAW_CLAWHUB_INDEX_URL", raising=False)

    fetcher = _make_fetcher(
        {
            "https://v/index.json": [
                {"name": "v-a", "downloadUrl": "https://e.com/a.zip"},
                {"name": "v-b", "downloadUrl": "https://e.com/b.zip"},
            ],
            "https://c/index.json": {
                "skills": [{"name": "c-a", "downloadUrl": "https://e.com/c.zip"}]
            },
        }
    )
    sync = MarketSync(
        pg_store=_FakePG(),
        vercel_index_url="https://v/index.json",
        clawhub_index_url="https://c/index.json",
        fetcher=fetcher,
    )
    summary = await sync.sync_to_db()
    assert summary["sources"]["vercel"] == {"ok": True, "count": 2}
    assert summary["sources"]["clawhub"] == {"ok": True, "count": 1}
    # _upsert stores to in-memory cache when pg is unavailable
    assert summary["total_upserted"] == 3


@pytest.mark.asyncio
async def test_market_sync_isolates_source_failure(monkeypatch):
    monkeypatch.delenv("XIAOPAW_VERCEL_SKILLS_INDEX_URL", raising=False)
    monkeypatch.delenv("XIAOPAW_CLAWHUB_INDEX_URL", raising=False)

    fetcher = _make_fetcher(
        {
            "https://v/index.json": [
                {"name": "v-a", "downloadUrl": "https://e.com/a.zip"}
            ],
            "https://c/index.json": RuntimeError("boom"),
        }
    )
    sync = MarketSync(
        pg_store=_FakePG(),
        vercel_index_url="https://v/index.json",
        clawhub_index_url="https://c/index.json",
        fetcher=fetcher,
    )
    summary = await sync.sync_to_db()
    assert summary["sources"]["vercel"]["ok"] is True
    assert summary["sources"]["vercel"]["count"] == 1
    assert summary["sources"]["clawhub"]["ok"] is False
    assert "boom" in summary["sources"]["clawhub"]["error"]


@pytest.mark.asyncio
async def test_market_sync_drops_invalid_entries(monkeypatch):
    monkeypatch.delenv("XIAOPAW_VERCEL_SKILLS_INDEX_URL", raising=False)

    fetcher = _make_fetcher(
        {
            "https://v/index.json": [
                {"name": "good", "downloadUrl": "https://e.com/g.zip"},
                {"name": "BAD", "downloadUrl": "https://e.com/b.zip"},  # bad case
                {"name": "no-url"},  # missing url
                {"name": "evil", "downloadUrl": "file:///etc/passwd"},
            ]
        }
    )
    sync = MarketSync(
        pg_store=_FakePG(),
        vercel_index_url="https://v/index.json",
        fetcher=fetcher,
    )
    summary = await sync.sync_to_db()
    assert summary["sources"]["vercel"]["count"] == 1


@pytest.mark.asyncio
async def test_market_sync_env_overrides_url(monkeypatch):
    monkeypatch.setenv("XIAOPAW_VERCEL_SKILLS_INDEX_URL", "https://override/idx.json")
    monkeypatch.delenv("XIAOPAW_CLAWHUB_INDEX_URL", raising=False)

    captured: list[str] = []

    async def _fetch(url: str):
        captured.append(url)
        return []

    sync = MarketSync(
        pg_store=_FakePG(),
        vercel_index_url="https://default/should-not-be-used.json",
        fetcher=_fetch,
    )
    await sync.sync_to_db()
    assert captured == ["https://override/idx.json"]


# ─── MarketRegistry.install ───────────────────────────────────


class _FakeRegistry:
    """Minimal SkillRegistry stub: just exposes user_dir + scan_all/sync_to_db."""

    def __init__(self, user_dir):
        self.user_dir = user_dir
        self.sync_to_db_calls = 0

    def scan_all(self):
        out = []
        for child in self.user_dir.iterdir():
            if child.is_dir():
                out.append(type("S", (), {"name": child.name})())
        return out

    def sync_to_db(self):
        self.sync_to_db_calls += 1
        return 0


def _build_skill_archive(tmp_path, name: str) -> bytes:
    src = tmp_path / "_src" / name
    src.mkdir(parents=True, exist_ok=True)
    (src / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test\nversion: 1.0.0\n---\nhello body\n",
        encoding="utf-8",
    )
    return pack_skill(src)


def _make_entry(name: str) -> MarketEntry:
    return MarketEntry(
        name=name,
        source_type="vercel",
        version="1.0.0",
        description="d",
        author="a",
        repo_url="https://r",
        install_url="https://e.com/x.zip",
    )


@pytest.mark.asyncio
async def test_market_registry_install_success(tmp_path, monkeypatch):
    user_skills = tmp_path / "user_skills"
    user_skills.mkdir()
    fake_reg = _FakeRegistry(user_skills)
    archive = _build_skill_archive(tmp_path, "my-skill")

    async def fetcher(url, max_bytes):
        assert url == "https://e.com/x.zip"
        return archive

    market = MarketRegistry(
        pg_store=None,
        skill_registry=fake_reg,
        archive_fetcher=fetcher,
    )
    monkeypatch.setattr(market, "get_market", lambda n: _make_entry(n) if n == "my-skill" else None)

    installed = await market.install("my-skill")
    assert installed == "my-skill"
    assert (user_skills / "my-skill" / "SKILL.md").exists()
    assert fake_reg.sync_to_db_calls == 1


@pytest.mark.asyncio
async def test_market_registry_install_not_found(tmp_path):
    user_skills = tmp_path / "user_skills"
    user_skills.mkdir()
    fake_reg = _FakeRegistry(user_skills)

    async def fetcher(url, max_bytes):  # pragma: no cover - should never be called
        raise AssertionError("fetcher should not be invoked")

    market = MarketRegistry(
        pg_store=None, skill_registry=fake_reg, archive_fetcher=fetcher
    )
    # get_market falls back to None because pg_store is None.
    with pytest.raises(MarketError) as ei:
        await market.install("missing")
    assert ei.value.code == "not_found"


@pytest.mark.asyncio
async def test_market_registry_install_name_mismatch_cleans_rogue_dir(
    tmp_path, monkeypatch
):
    user_skills = tmp_path / "user_skills"
    user_skills.mkdir()
    fake_reg = _FakeRegistry(user_skills)
    # Archive declares ``actual-name`` while the user clicked ``displayed-name``.
    archive = _build_skill_archive(tmp_path, "actual-name")

    async def fetcher(url, max_bytes):
        return archive

    market = MarketRegistry(
        pg_store=None, skill_registry=fake_reg, archive_fetcher=fetcher
    )
    monkeypatch.setattr(
        market, "get_market",
        lambda n: _make_entry("displayed-name") if n == "displayed-name" else None,
    )

    with pytest.raises(MarketError) as ei:
        await market.install("displayed-name")
    assert ei.value.code == "name_mismatch"
    # The rogue dir must be cleaned up so a follow-up legitimate install works.
    assert not (user_skills / "actual-name").exists()


@pytest.mark.asyncio
async def test_market_registry_install_propagates_validation_error(
    tmp_path, monkeypatch
):
    user_skills = tmp_path / "user_skills"
    user_skills.mkdir()
    fake_reg = _FakeRegistry(user_skills)

    async def fetcher(url, max_bytes):
        return b"not-a-zip"

    market = MarketRegistry(
        pg_store=None, skill_registry=fake_reg, archive_fetcher=fetcher
    )
    monkeypatch.setattr(market, "get_market", lambda n: _make_entry(n))

    with pytest.raises(MarketError) as ei:
        await market.install("x")
    # Maps to a packager validation code, not the catch-all "install_failed".
    assert ei.value.code in ("bad_zip", "missing_skill_md")


@pytest.mark.asyncio
async def test_market_registry_install_download_failure_wraps(
    tmp_path, monkeypatch
):
    user_skills = tmp_path / "user_skills"
    user_skills.mkdir()
    fake_reg = _FakeRegistry(user_skills)

    async def fetcher(url, max_bytes):
        raise ConnectionError("network down")

    market = MarketRegistry(
        pg_store=None, skill_registry=fake_reg, archive_fetcher=fetcher
    )
    monkeypatch.setattr(market, "get_market", lambda n: _make_entry(n))

    with pytest.raises(MarketError) as ei:
        await market.install("x")
    assert ei.value.code == "download_failed"
    assert "network down" in ei.value.message


# ─── HTTP e2e through aiohttp test_client ────────────────────────────────────
#
# Spec §10 V3: end-to-end coverage of the four /api/frontend/market/* routes
# without depending on Postgres or real network. We wire a real ``MarketRegistry``
# + a stub ``MarketSync`` into an aiohttp app and exercise the handlers.


class _FakeMarketSync:
    def __init__(self):
        self.calls = 0

    async def sync_to_db(self):
        self.calls += 1
        return {"vercel": {"upserted": 1}, "clawhub": {"upserted": 0}}


class _FakeRegistryWithList(_FakeRegistry):
    """Adds ``list_all`` so handle_list_skills doesn't blow up if hit."""

    def list_all(self):
        return []

    def get(self, name):
        return None


from contextlib import asynccontextmanager


def _build_market_app(tmp_path, monkeypatch):
    from aiohttp import web

    from xiaopaw.skills_mgmt.api import register_routes

    user_skills = tmp_path / "user_skills"
    user_skills.mkdir()
    skill_reg = _FakeRegistryWithList(user_skills)
    archive = _build_skill_archive(tmp_path, "demo-skill")

    async def archive_fetcher(url, max_bytes):
        return archive

    market = MarketRegistry(
        pg_store=None, skill_registry=skill_reg, archive_fetcher=archive_fetcher
    )

    catalog = {
        "demo-skill": MarketEntry(
            name="demo-skill",
            source_type="vercel",
            version="1.0.0",
            description="demo",
            author="alice",
            repo_url="https://github.com/x/y",
            install_url="https://e.com/demo.zip",
        ),
    }
    monkeypatch.setattr(market, "get_market", lambda n: catalog.get(n))
    monkeypatch.setattr(
        market,
        "list_market",
        lambda search=None, source_type=None: [
            e for e in catalog.values()
            if (not search or search.lower() in e.name.lower())
            and (not source_type or e.source_type == source_type)
        ],
    )

    sync = _FakeMarketSync()

    app = web.Application()
    app["skill_registry"] = skill_reg
    app["market_registry"] = market
    app["market_sync"] = sync
    register_routes(app)
    return app, skill_reg, sync


@asynccontextmanager
async def _client_for(app):
    """Wrap aiohttp's TestServer/TestClient without pytest-aiohttp."""
    from aiohttp.test_utils import TestClient, TestServer

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_e2e_market_list_install_refresh(tmp_path, monkeypatch):
    app, skill_reg, sync = _build_market_app(tmp_path, monkeypatch)
    async with _client_for(app) as client:
        # 1) list market -- catalog has one not-yet-installed entry
        resp = await client.get("/api/frontend/market/skills")
        assert resp.status == 200
        data = await resp.json()
        assert data["total"] == 1
        assert data["skills"][0]["name"] == "demo-skill"
        assert data["skills"][0]["installed"] is False

        # 2) get single entry
        resp = await client.get("/api/frontend/market/skills/demo-skill")
        assert resp.status == 200
        detail = await resp.json()
        assert detail["name"] == "demo-skill"
        assert detail["installed"] is False

        # 3) install it -- archive_fetcher returns a real zip
        resp = await client.post("/api/frontend/market/skills/demo-skill/install")
        assert resp.status == 200, await resp.text()
        body = await resp.json()
        assert body == {"ok": True, "name": "demo-skill"}
        assert skill_reg.sync_to_db_calls == 1

        # 4) list again -- now installed flag flips
        resp = await client.get("/api/frontend/market/skills")
        data = await resp.json()
        assert data["skills"][0]["installed"] is True

        # 5) install without overwrite -> 409 exists
        resp = await client.post("/api/frontend/market/skills/demo-skill/install")
        assert resp.status == 409
        err = await resp.json()
        assert err["error"] == "exists"

        # 6) refresh triggers MarketSync.sync_to_db once
        resp = await client.post("/api/frontend/market/refresh")
        assert resp.status == 200
        summary = await resp.json()
        assert summary["ok"] is True
        assert sync.calls == 1


@pytest.mark.asyncio
async def test_e2e_market_install_unknown_returns_404(tmp_path, monkeypatch):
    app, *_ = _build_market_app(tmp_path, monkeypatch)
    async with _client_for(app) as client:
        resp = await client.post("/api/frontend/market/skills/missing/install")
        assert resp.status == 404
        err = await resp.json()
        assert err["error"] == "not_found"


@pytest.mark.asyncio
async def test_e2e_market_search_filter(tmp_path, monkeypatch):
    app, *_ = _build_market_app(tmp_path, monkeypatch)
    async with _client_for(app) as client:
        resp = await client.get("/api/frontend/market/skills?search=DEMO")
        assert resp.status == 200
        data = await resp.json()
        assert data["total"] == 1

        resp = await client.get("/api/frontend/market/skills?search=nope")
        assert resp.status == 200
        data = await resp.json()
        assert data["total"] == 0


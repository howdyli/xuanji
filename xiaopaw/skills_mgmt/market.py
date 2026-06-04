"""Skill market: remote-repository index sync + one-click install.

Architecture
------------
- ``MarketSync`` periodically fetches manifest indexes from Vercel Skills
  and ClawHub, then upserts entries into the ``skill_market`` table. It is
  driven by a background asyncio task in ``main.py`` (see ``MarketSyncRunner``
  for that wrapper).
- ``MarketRegistry`` exposes read APIs (``list_market``/``get_market``) and
  the install action used by HTTP handlers. (Install logic lives in T2.)

Adapter contract
----------------
Each remote source publishes a JSON index. The adapter functions
(``_parse_vercel_entry`` / ``_parse_clawhub_entry``) translate one raw item
into a :class:`MarketEntry`. We persist the raw item in ``manifest_json`` so
upstream protocol drift can be diagnosed without re-fetching.

The Vercel Skills / ClawHub URLs are placeholders; both default values can be
overridden via ``config.yaml`` or env (``XIAOPAW_VERCEL_SKILLS_INDEX_URL`` /
``XIAOPAW_CLAWHUB_INDEX_URL``) so the protocol can be re-pointed without code
changes when the real upstream is published.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# kebab-case identifier; matches the convention used by SkillRegistry.
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

JsonFetcher = Callable[[str], Awaitable[Any]]
BytesFetcher = Callable[[str, int], Awaitable[bytes]]


class MarketError(Exception):
    """Install/sync errors with a stable code for HTTP mapping."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


# ─── MarketEntry ──────────────────────────────────────────────────────────────


@dataclass
class MarketEntry:
    """Single market-listed skill (Vercel/ClawHub adapter output)."""

    name: str
    source_type: str  # 'vercel' | 'clawhub'
    version: str
    description: str
    author: str
    repo_url: str
    install_url: str
    manifest_json: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime | None = None
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "MarketEntry":
        manifest = row.get("manifest_json") or {}
        if isinstance(manifest, str):
            try:
                manifest = json.loads(manifest)
            except json.JSONDecodeError:
                manifest = {}
        return cls(
            name=row["name"],
            source_type=row["source_type"],
            version=row.get("version", "") or "",
            description=row.get("description", "") or "",
            author=row.get("author", "") or "",
            repo_url=row.get("repo_url", "") or "",
            install_url=row.get("install_url", "") or "",
            manifest_json=manifest,
            updated_at=row.get("updated_at"),
            fetched_at=row.get("fetched_at") or datetime.now(timezone.utc),
        )

    def to_dict(self, *, installed: bool = False) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_type": self.source_type,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "repo_url": self.repo_url,
            "install_url": self.install_url,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "fetched_at": self.fetched_at.isoformat(),
            "installed": installed,
        }


# ─── Adapters ────────────────────────────────────────────────────────────────


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        # accept trailing 'Z'
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_vercel_entry(item: dict[str, Any]) -> MarketEntry | None:
    """Translate a Vercel Skills index item.

    Assumed schema (subject to change once upstream protocol is published):
        {
            "name": "ppt-master",
            "version": "1.0.0",
            "description": "...",
            "author": "vercel",
            "repository": "https://github.com/vercel/skills/tree/main/ppt-master",
            "downloadUrl": "https://.../ppt-master.zip",
            "updatedAt": "2024-12-01T10:00:00Z"
        }
    """
    if not isinstance(item, dict):
        return None
    name = (item.get("name") or "").strip()
    install_url = (item.get("downloadUrl") or item.get("download_url") or "").strip()
    if not name or not _NAME_RE.match(name):
        return None
    if not install_url.startswith(("http://", "https://")):
        return None
    return MarketEntry(
        name=name,
        source_type="vercel",
        version=str(item.get("version", "")).strip(),
        description=(item.get("description") or "").strip(),
        author=(item.get("author") or "").strip(),
        repo_url=(item.get("repository") or item.get("repo_url") or "").strip(),
        install_url=install_url,
        manifest_json=dict(item),
        updated_at=_parse_iso(item.get("updatedAt") or item.get("updated_at")),
    )


def _parse_clawhub_entry(item: dict[str, Any]) -> MarketEntry | None:
    """Translate a ClawHub index item.

    ClawHub protocol details are TBD (T3); for now we accept the same shape
    as Vercel, with ``source_type='clawhub'``. Once the real schema is known,
    update this adapter only.
    """
    entry = _parse_vercel_entry(item)
    if entry is None:
        return None
    entry.source_type = "clawhub"
    return entry


def _extract_index_items(payload: Any) -> list[dict[str, Any]]:
    """Accept either ``[items]`` or ``{"skills": [items]}`` wrappers."""
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("skills") or payload.get("items") or []
    else:
        items = []
    return [it for it in items if isinstance(it, dict)]


# ─── MarketSync ───────────────────────────────────────────────────────────────


class MarketSync:
    """Pull remote indexes -> upsert into ``skill_market`` table."""

    def __init__(
        self,
        pg_store: Any,
        vercel_index_url: str = "",
        clawhub_index_url: str = "",
        fetch_timeout_seconds: float = 60.0,
        fetcher: JsonFetcher | None = None,
    ) -> None:
        self._pg = pg_store
        self._vercel_url = (
            os.environ.get("XIAOPAW_VERCEL_SKILLS_INDEX_URL")
            or vercel_index_url
        )
        self._clawhub_url = (
            os.environ.get("XIAOPAW_CLAWHUB_INDEX_URL") or clawhub_index_url
        )
        self._timeout = fetch_timeout_seconds
        self._fetcher = fetcher or self._default_fetch_json
        self._lock = asyncio.Lock()
        # In-memory fallback when pg_store is unavailable.
        self._mem_entries: dict[str, MarketEntry] = {}

    async def sync_to_db(self) -> dict[str, Any]:
        """Run one sync cycle. Source failures are isolated (logged, not raised).

        Returns a per-source summary suitable for logging / HTTP response.
        """
        async with self._lock:
            tasks = []
            if self._vercel_url:
                tasks.append(("vercel", self._fetch_vercel()))
            if self._clawhub_url:
                tasks.append(("clawhub", self._fetch_clawhub()))

            if not tasks:
                logger.warning("MarketSync: no sources configured, skip")
                return {"sources": {}, "total_upserted": 0}

            results = await asyncio.gather(
                *(t for _, t in tasks), return_exceptions=True
            )

            summary: dict[str, Any] = {"sources": {}, "total_upserted": 0}
            entries: list[MarketEntry] = []
            for (src, _), res in zip(tasks, results):
                if isinstance(res, Exception):
                    logger.warning("MarketSync %s fetch failed: %s", src, res)
                    summary["sources"][src] = {"ok": False, "error": str(res)}
                    continue
                summary["sources"][src] = {"ok": True, "count": len(res)}
                entries.extend(res)

            upserted = await asyncio.to_thread(self._upsert, entries)
            summary["total_upserted"] = upserted
            logger.info("MarketSync done: %s", summary)
            return summary

    async def _fetch_vercel(self) -> list[MarketEntry]:
        payload = await self._fetcher(self._vercel_url)
        items = _extract_index_items(payload)
        out = [_parse_vercel_entry(it) for it in items]
        return [e for e in out if e is not None]

    async def _fetch_clawhub(self) -> list[MarketEntry]:
        payload = await self._fetcher(self._clawhub_url)
        items = _extract_index_items(payload)
        out = [_parse_clawhub_entry(it) for it in items]
        return [e for e in out if e is not None]

    async def _default_fetch_json(self, url: str) -> Any:
        # Imported lazily so the module is importable without aiohttp at
        # collection time (e.g. from unit tests that inject a fake fetcher).
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=self._timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)

    def _upsert(self, entries: list[MarketEntry]) -> int:
        """Sync upsert (called via ``to_thread``). Falls back to in-memory."""
        if not entries:
            return 0
        # Always update in-memory cache (used by MarketRegistry when no PG).
        for e in entries:
            self._mem_entries[e.name] = e
        if not self._pg or not self._pg._ensure_connection():
            return len(entries)
        try:
            with self._pg._conn.cursor() as cur:
                for e in entries:
                    cur.execute(
                        """INSERT INTO skill_market (
                                name, source_type, version, description,
                                author, repo_url, install_url,
                                manifest_json, updated_at, fetched_at
                           ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, NOW()
                           )
                           ON CONFLICT (name) DO UPDATE SET
                                source_type   = EXCLUDED.source_type,
                                version       = EXCLUDED.version,
                                description   = EXCLUDED.description,
                                author        = EXCLUDED.author,
                                repo_url      = EXCLUDED.repo_url,
                                install_url   = EXCLUDED.install_url,
                                manifest_json = EXCLUDED.manifest_json,
                                updated_at    = EXCLUDED.updated_at,
                                fetched_at    = NOW()
                        """,
                        (
                            e.name,
                            e.source_type,
                            e.version,
                            e.description,
                            e.author,
                            e.repo_url,
                            e.install_url,
                            json.dumps(e.manifest_json, ensure_ascii=False),
                            e.updated_at,
                        ),
                    )
            self._pg._conn.commit()
            return len(entries)
        except Exception as exc:
            try:
                self._pg._conn.rollback()
            except Exception:
                pass
            logger.warning("MarketSync upsert failed: %s", exc)
            return 0


# ─── MarketRegistry ───────────────────────────────────────────────────────────


class MarketRegistry:
    """Read APIs over the cached market index + one-click install.

    The registry intentionally does NOT trigger remote sync. ``MarketSync`` is
    the only writer; this class just queries the DB and performs install via
    ``unpack_skill``. Keeping the responsibilities split avoids a slow remote
    fetch on every page load.
    """

    def __init__(
        self,
        pg_store: Any,
        skill_registry: Any,
        install_max_bytes: int = 20 * 1024 * 1024,
        fetch_timeout_seconds: float = 60.0,
        archive_fetcher: BytesFetcher | None = None,
        market_sync: "MarketSync | None" = None,
    ) -> None:
        self._pg = pg_store
        self._reg = skill_registry
        self._install_max_bytes = install_max_bytes
        self._timeout = fetch_timeout_seconds
        self._archive_fetcher = archive_fetcher or self._default_fetch_archive
        # Reference to MarketSync so we can read in-memory entries when no PG.
        self._sync = market_sync

    # ─── List / Get ──────────────────────────────────────────────────────

    def list_market(
        self,
        *,
        search: str | None = None,
        source_type: str | None = None,
    ) -> list[MarketEntry]:
        # Fast path: PostgreSQL backed.
        if self._pg and self._pg._ensure_connection():
            try:
                import psycopg2.extras

                sql = "SELECT * FROM skill_market"
                params: list[Any] = []
                clauses: list[str] = []
                if source_type in ("vercel", "clawhub"):
                    clauses.append("source_type = %s")
                    params.append(source_type)
                if search:
                    clauses.append("(name ILIKE %s OR description ILIKE %s)")
                    like = f"%{search}%"
                    params.extend([like, like])
                if clauses:
                    sql += " WHERE " + " AND ".join(clauses)
                sql += " ORDER BY name ASC"
                with self._pg._conn.cursor(
                    cursor_factory=psycopg2.extras.RealDictCursor
                ) as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
                return [MarketEntry.from_row(dict(r)) for r in rows]
            except Exception as exc:
                logger.warning("list_market failed: %s", exc)
                return []
        # In-memory fallback (no PostgreSQL).
        items = list(self._sync._mem_entries.values()) if self._sync else []
        if source_type in ("vercel", "clawhub"):
            items = [e for e in items if e.source_type == source_type]
        if search:
            s = search.lower()
            items = [e for e in items if s in e.name.lower() or s in e.description.lower()]
        return sorted(items, key=lambda e: e.name)

    def get_market(self, name: str) -> MarketEntry | None:
        # Fast path: PostgreSQL backed.
        if self._pg and self._pg._ensure_connection():
            try:
                import psycopg2.extras

                with self._pg._conn.cursor(
                    cursor_factory=psycopg2.extras.RealDictCursor
                ) as cur:
                    cur.execute("SELECT * FROM skill_market WHERE name = %s", (name,))
                    row = cur.fetchone()
                return MarketEntry.from_row(dict(row)) if row else None
            except Exception as exc:
                logger.warning("get_market failed: %s", exc)
                return None
        # In-memory fallback (no PostgreSQL).
        if self._sync:
            return self._sync._mem_entries.get(name)
        return None

    def installed_names(self) -> set[str]:
        """Names of skills currently present on disk (builtin + user)."""
        if not self._reg:
            return set()
        try:
            return {s.name for s in self._reg.scan_all()}
        except Exception as exc:
            logger.warning("installed_names failed: %s", exc)
            return set()

    # ─── Install ─────────────────────────────────────────────────────────

    async def install(self, name: str, *, overwrite: bool = False) -> str:
        """Download the archive for ``name`` and unpack into ``user_skills``.

        Returns the installed skill name (= unpacked SKILL.md frontmatter
        ``name``, which must equal the requested name to defend against
        index/archive name spoofing).

        Raises :class:`MarketError` on any validation/network failure.
        Caller is responsible for HTTP error mapping.
        """
        # Lazy import: avoid circular when MarketRegistry constructed at startup.
        from xiaopaw.skills_mgmt.packager import unpack_skill
        from xiaopaw.skills_mgmt.validator import ValidationError

        entry = self.get_market(name)
        if entry is None:
            raise MarketError("not_found", f"market entry not found: {name}")

        try:
            archive_bytes = await self._archive_fetcher(
                entry.install_url, self._install_max_bytes
            )
        except MarketError:
            raise
        except Exception as exc:
            logger.warning("market install fetch failed: %s", exc)
            raise MarketError("download_failed", str(exc))

        if not archive_bytes:
            raise MarketError("empty_archive", "downloaded archive is empty")
        if len(archive_bytes) > self._install_max_bytes:
            raise MarketError("too_large", "archive exceeds install_max_bytes")

        try:
            unpacked_name, _target = await asyncio.to_thread(
                unpack_skill,
                archive_bytes,
                self._reg.user_dir,
                max_archive_bytes=self._install_max_bytes,
                overwrite=overwrite,
            )
        except ValidationError as exc:
            raise MarketError(exc.code, exc.message)

        # Defend against name spoofing: archive's SKILL.md must match the
        # market entry name we displayed to the user.
        if unpacked_name != name:
            # Roll back: best-effort cleanup of the rogue dir.
            try:
                import shutil

                rogue = self._reg.user_dir / unpacked_name
                if rogue.exists():
                    shutil.rmtree(rogue, ignore_errors=True)
            except Exception:
                pass
            raise MarketError(
                "name_mismatch",
                f"archive name '{unpacked_name}' != market name '{name}'",
            )

        # Refresh DB metadata for the new skill.
        try:
            self._reg.sync_to_db()
        except Exception as exc:
            logger.warning("sync_to_db after install failed: %s", exc)

        return unpacked_name

    async def _default_fetch_archive(self, url: str, max_bytes: int) -> bytes:
        """Stream archive bytes with a hard size cap."""
        if not url.startswith(("http://", "https://")):
            raise MarketError("bad_url", f"non-http URL: {url}")
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=self._timeout)
        buf = bytearray()
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise MarketError(
                            "too_large",
                            f"archive exceeds {max_bytes} bytes",
                        )
        return bytes(buf)

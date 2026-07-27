"""Per-session sandbox pool — 短期建议 #9 会话级沙箱隔离（MVP）。

Each session gets its own AIO-Sandbox container so that files, processes and
browser state created in one conversation can never leak into another. The
pool drives the local ``docker`` CLI (no extra Python deps) and is disabled by
default (``sandbox.per_session: false``). Any failure — docker missing, image
pull error, port exhaustion — falls back to the shared sandbox URL so skill
execution never breaks outright.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Container names must be [a-zA-Z0-9][a-zA-Z0-9_.-]*; session ids may not be.
_NAME_SAFE_RE = re.compile(r"[^a-zA-Z0-9_.-]")
_CONTAINER_PREFIX = "xiaopaw-sbx-"

# AIO-Sandbox serves HTTP (incl. /mcp) on this port inside the container.
_SANDBOX_INTERNAL_PORT = 8080


def _container_name(session_id: str) -> str:
    return _CONTAINER_PREFIX + _NAME_SAFE_RE.sub("-", session_id)[:48]


class SandboxPool:
    """Manage one AIO-Sandbox container per session, with LRU + idle eviction."""

    def __init__(
        self,
        shared_url: str,
        image: str = "ghcr.io/agent-infra/sandbox:latest",
        port_start: int = 8100,
        max_containers: int = 5,
        idle_ttl_s: int = 1800,
        ready_timeout_s: float = 60.0,
    ) -> None:
        self._shared_url = shared_url
        self._image = image
        self._port_start = port_start
        self._max = max_containers
        self._idle_ttl = idle_ttl_s
        self._ready_timeout = ready_timeout_s
        # session_id -> [port, last_used_monotonic]
        self._alloc: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    # ── public API ──────────────────────────────────────────────────────────

    async def acquire(self, session_id: str) -> str:
        """Return the MCP URL of *session_id*'s dedicated sandbox.

        Starts (or reuses) the container on demand. Never raises: any failure
        falls back to the shared sandbox URL configured in ``sandbox.url``.
        """
        try:
            async with self._lock:
                self._reap_idle_locked_names()  # collect, stop outside lock is
                # not needed for MVP: stopping via docker is quick and rare.
                port = await self._ensure_container_locked(session_id)
            return f"http://127.0.0.1:{port}/mcp"
        except Exception as exc:
            logger.warning(
                "sandbox pool: per-session sandbox unavailable for %s (%s: %s); "
                "falling back to shared sandbox",
                session_id, type(exc).__name__, exc,
            )
            return self._shared_url

    async def shutdown(self) -> None:
        """Stop all pool-owned containers (best-effort)."""
        async with self._lock:
            for sid in list(self._alloc):
                try:
                    await self._run_docker("stop", _container_name(sid))
                except Exception as exc:
                    logger.debug("sandbox pool: stop %s failed: %s", sid, exc)
                self._alloc.pop(sid, None)

    # ── internals ───────────────────────────────────────────────────────────

    async def _ensure_container_locked(self, session_id: str) -> int:
        entry = self._alloc.get(session_id)
        if entry is not None:
            if await self._is_running(session_id):
                entry[1] = time.monotonic()
                return int(entry[0])
            # Container died (crash / manual stop): drop and restart below.
            self._alloc.pop(session_id, None)

        if len(self._alloc) >= self._max:
            await self._evict_lru_locked()

        port = self._pick_free_port_locked()
        await self._run_docker(
            "run", "-d", "--rm",
            "--name", _container_name(session_id),
            "-p", f"127.0.0.1:{port}:{_SANDBOX_INTERNAL_PORT}",
            self._image,
        )
        await self._wait_ready(port)
        self._alloc[session_id] = [port, time.monotonic()]
        logger.info(
            "sandbox pool: started container for session=%s port=%d "
            "(pool %d/%d)", session_id, port, len(self._alloc), self._max,
        )
        return port

    def _pick_free_port_locked(self) -> int:
        used = {int(e[0]) for e in self._alloc.values()}
        for port in range(self._port_start, self._port_start + self._max):
            if port not in used:
                return port
        raise RuntimeError("sandbox pool: no free port slot")

    async def _evict_lru_locked(self) -> None:
        lru_sid = min(self._alloc, key=lambda s: self._alloc[s][1])
        logger.info("sandbox pool: evicting LRU session=%s", lru_sid)
        try:
            await self._run_docker("stop", _container_name(lru_sid))
        except Exception as exc:
            logger.debug("sandbox pool: evict stop failed: %s", exc)
        self._alloc.pop(lru_sid, None)

    def _reap_idle_locked_names(self) -> None:
        """Drop bookkeeping for sessions idle beyond TTL (stop is async fired)."""
        now = time.monotonic()
        for sid in [s for s, e in self._alloc.items() if now - e[1] > self._idle_ttl]:
            logger.info("sandbox pool: reaping idle session=%s", sid)
            asyncio.ensure_future(self._stop_quiet(_container_name(sid)))
            self._alloc.pop(sid, None)

    async def _stop_quiet(self, name: str) -> None:
        try:
            await self._run_docker("stop", name)
        except Exception as exc:
            logger.debug("sandbox pool: reap stop %s failed: %s", name, exc)

    async def _is_running(self, session_id: str) -> bool:
        try:
            out = await self._run_docker(
                "inspect", "-f", "{{.State.Running}}", _container_name(session_id)
            )
            return out.strip() == "true"
        except Exception:
            return False

    async def _run_docker(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(
                f"docker {' '.join(args[:2])} failed "
                f"(rc={proc.returncode}): {stderr.decode(errors='replace')[:300]}"
            )
        return stdout.decode(errors="replace")

    async def _wait_ready(self, port: int) -> None:
        """Poll the sandbox HTTP origin until it answers or timeout."""
        import aiohttp

        origin = f"http://127.0.0.1:{port}/"
        deadline = time.monotonic() + self._ready_timeout
        timeout = aiohttp.ClientTimeout(total=3)
        while time.monotonic() < deadline:
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(origin) as resp:
                        if resp.status < 500:
                            return
            except Exception:
                pass
            await asyncio.sleep(1.0)
        raise RuntimeError(f"sandbox at {origin} not ready in {self._ready_timeout}s")


def shared_url_origin(shared_url: str) -> str:
    """Helper for logs: MCP URL → HTTP origin."""
    parts = urlsplit(shared_url)
    return f"{parts.scheme}://{parts.netloc}/"

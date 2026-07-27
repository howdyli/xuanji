"""Tests for SandboxPool — 会话级沙箱池（短期#9）。

docker CLI 与就绪探测均以 mock 替代，验证分配 / 复用 / 回退 / 淘汰逻辑。
"""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock

from xiaopaw.sandbox_pool import SandboxPool, _container_name

SHARED = "http://localhost:8030/mcp"


def _make_pool(**kwargs) -> SandboxPool:
    pool = SandboxPool(shared_url=SHARED, port_start=9100, max_containers=3, **kwargs)
    pool._run_docker = AsyncMock(return_value="")  # type: ignore[method-assign]
    pool._wait_ready = AsyncMock()  # type: ignore[method-assign]
    pool._is_running = AsyncMock(return_value=True)  # type: ignore[method-assign]
    return pool


class TestContainerName:
    def test_sanitizes_unsafe_chars(self):
        """会话 ID 中的非法字符被替换，前缀固定"""
        name = _container_name("p2p:web_admin/s-001")
        assert name.startswith("xiaopaw-sbx-")
        assert ":" not in name and "/" not in name

    def test_length_capped(self):
        name = _container_name("s" * 200)
        assert len(name) <= len("xiaopaw-sbx-") + 48


class TestAcquire:
    @pytest.mark.asyncio
    async def test_starts_container_and_returns_url(self):
        """首次 acquire 启动容器并返回独立端口的 MCP URL"""
        pool = _make_pool()
        url = await pool.acquire("s-001")
        assert url == "http://127.0.0.1:9100/mcp"
        run_call = pool._run_docker.call_args_list[0]
        assert run_call.args[0] == "run"
        assert "xiaopaw-sbx-s-001" in run_call.args
        pool._wait_ready.assert_awaited_once_with(9100)

    @pytest.mark.asyncio
    async def test_reuses_running_container(self):
        """同一会话重复 acquire 复用容器，不再 docker run"""
        pool = _make_pool()
        url1 = await pool.acquire("s-001")
        runs_before = sum(
            1 for c in pool._run_docker.call_args_list if c.args[0] == "run"
        )
        url2 = await pool.acquire("s-001")
        runs_after = sum(
            1 for c in pool._run_docker.call_args_list if c.args[0] == "run"
        )
        assert url1 == url2
        assert runs_before == runs_after == 1

    @pytest.mark.asyncio
    async def test_distinct_sessions_get_distinct_ports(self):
        """不同会话分配不同端口"""
        pool = _make_pool()
        urls = {await pool.acquire(f"s-{i}") for i in range(3)}
        assert urls == {
            "http://127.0.0.1:9100/mcp",
            "http://127.0.0.1:9101/mcp",
            "http://127.0.0.1:9102/mcp",
        }

    @pytest.mark.asyncio
    async def test_falls_back_to_shared_on_docker_failure(self):
        """docker 失败时回退共享沙箱 URL，不抛异常"""
        pool = _make_pool()
        pool._run_docker = AsyncMock(side_effect=RuntimeError("docker not found"))
        url = await pool.acquire("s-err")
        assert url == SHARED

    @pytest.mark.asyncio
    async def test_restarts_dead_container(self):
        """容器已死时重新启动（分配表先清理再 run）"""
        pool = _make_pool()
        await pool.acquire("s-001")
        pool._is_running = AsyncMock(return_value=False)
        await pool.acquire("s-001")
        runs = sum(1 for c in pool._run_docker.call_args_list if c.args[0] == "run")
        assert runs == 2


class TestEviction:
    @pytest.mark.asyncio
    async def test_lru_evicted_when_pool_full(self):
        """池满时淘汰最久未用的会话"""
        pool = _make_pool()
        for i in range(3):
            await pool.acquire(f"s-{i}")
            await asyncio.sleep(0.01)
        await pool.acquire("s-3")  # 触发淘汰 s-0
        assert "s-0" not in pool._alloc
        assert "s-3" in pool._alloc
        stop_calls = [c for c in pool._run_docker.call_args_list if c.args[0] == "stop"]
        assert any("xiaopaw-sbx-s-0" in c.args for c in stop_calls)

    @pytest.mark.asyncio
    async def test_shutdown_stops_all(self):
        """shutdown 停掉全部池内容器并清空分配表"""
        pool = _make_pool()
        for i in range(2):
            await pool.acquire(f"s-{i}")
        await pool.shutdown()
        assert pool._alloc == {}
        stop_calls = [c for c in pool._run_docker.call_args_list if c.args[0] == "stop"]
        assert len(stop_calls) == 2


class TestIdleReap:
    @pytest.mark.asyncio
    async def test_idle_session_reaped(self):
        """超过 idle TTL 的会话在下次 acquire 时被回收"""
        pool = _make_pool(idle_ttl_s=60)
        await pool.acquire("s-old")
        # 手动把 last_used 拨回过期
        pool._alloc["s-old"][1] -= 120
        await pool.acquire("s-new")
        assert "s-old" not in pool._alloc
        assert "s-new" in pool._alloc

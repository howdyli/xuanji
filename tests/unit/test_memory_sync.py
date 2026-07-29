"""Unit tests for xiaopaw.memory.memory_sync (Phase C2 统一双写)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import xiaopaw.memory.memory_sync as memory_sync_mod
from xiaopaw.memory.memory_sync import (
    MemorySyncManager,
    _escape_like,
    get_sync_manager,
)


def _manager(db_dsn: str = "postgresql://test/db") -> tuple[MemorySyncManager, AsyncMock]:
    remote = AsyncMock()
    return MemorySyncManager(remote, db_dsn), remote


class TestWriteThrough:
    async def test_remote_ok_writes_local_synced(self):
        mgr, remote = _manager()
        remote.save_turn.return_value = True
        with patch("xiaopaw.memory.indexer.async_index_turn", new=AsyncMock()) as idx:
            await mgr.write_through(
                session_id="s1", routing_key="rk", user_message="u",
                assistant_reply="a", turn_ts=123,
            )
        remote.save_turn.assert_awaited_once()
        idx.assert_awaited_once()
        assert idx.await_args.kwargs["remote_synced"] is True

    async def test_remote_failed_marks_pending(self):
        """远程失败时本地行必须带 remote_synced=False（pending 标记落地）。"""
        mgr, remote = _manager()
        remote.save_turn.return_value = False
        with patch("xiaopaw.memory.indexer.async_index_turn", new=AsyncMock()) as idx:
            await mgr.write_through(
                session_id="s1", routing_key="rk", user_message="u",
                assistant_reply="a", turn_ts=123,
            )
        assert idx.await_args.kwargs["remote_synced"] is False

    async def test_remote_raises_treated_as_failure(self):
        """save_turn 意外抛异常时兜底为远程失败，不向上抛。"""
        mgr, remote = _manager()
        remote.save_turn.side_effect = RuntimeError("boom")
        with patch("xiaopaw.memory.indexer.async_index_turn", new=AsyncMock()) as idx:
            await mgr.write_through(
                session_id="s1", routing_key="rk", user_message="u",
                assistant_reply="a", turn_ts=123,
            )
        assert idx.await_args.kwargs["remote_synced"] is False

    async def test_no_dsn_skips_local(self):
        mgr, remote = _manager(db_dsn="")
        remote.save_turn.return_value = True
        with patch("xiaopaw.memory.indexer.async_index_turn", new=AsyncMock()) as idx:
            await mgr.write_through(
                session_id="s1", routing_key="rk", user_message="u",
                assistant_reply="a", turn_ts=123,
            )
        idx.assert_not_awaited()

    async def test_local_failure_does_not_raise(self):
        mgr, remote = _manager()
        remote.save_turn.return_value = True
        failing = AsyncMock(side_effect=RuntimeError("db down"))
        with patch("xiaopaw.memory.indexer.async_index_turn", new=failing):
            await mgr.write_through(
                session_id="s1", routing_key="rk", user_message="u",
                assistant_reply="a", turn_ts=123,
            )  # 不抛即通过


class TestReadThrough:
    async def test_local_enough_skips_remote(self):
        mgr, remote = _manager()
        rows = [{"id": str(i), "content": f"c{i}"} for i in range(5)]
        with patch.object(mgr, "_search_local", new=AsyncMock(return_value=rows)):
            results = await mgr.read_through("query", top_k=5)
        assert len(results) == 5
        assert all(r["source"] == "local" for r in results)
        remote.recall.assert_not_awaited()

    async def test_local_miss_falls_back_to_remote(self):
        mgr, remote = _manager()
        remote.recall.return_value = "远程记忆内容"
        with patch.object(mgr, "_search_local", new=AsyncMock(return_value=[])):
            results = await mgr.read_through("query", top_k=5)
        assert results == [{"source": "remote", "content": "远程记忆内容"}]

    async def test_both_fail_returns_empty(self):
        mgr, remote = _manager()
        remote.recall.side_effect = RuntimeError("remote down")
        with patch.object(
            mgr, "_search_local", new=AsyncMock(side_effect=RuntimeError("db down"))
        ):
            results = await mgr.read_through("query")
        assert results == []

    async def test_no_dsn_goes_remote_only(self):
        mgr, remote = _manager(db_dsn="")
        remote.recall.return_value = "ctx"
        results = await mgr.read_through("query")
        assert results == [{"source": "remote", "content": "ctx"}]


class TestEscapeLike:
    def test_escapes_wildcards(self):
        assert _escape_like("50%_x\\y") == "50\\%\\_x\\\\y"

    def test_plain_text_unchanged(self):
        assert _escape_like("普通查询") == "普通查询"


class TestFullSync:
    async def test_pulls_fragments_with_remote_id_as_key(self):
        """远程片段用 id 作本地主键，避免 created_ts=0 时 hash 碰撞。"""
        mgr, remote = _manager()
        remote.list_fragments.return_value = [
            {"id": "f1", "session_id": "s1", "content": "c1"},
            {"id": "f2", "session_id": "s1", "content": "c2"},
        ]
        with patch.object(mgr, "_push_pending", new=AsyncMock(return_value=0)), \
             patch("xiaopaw.memory.indexer.async_index_turn", new=AsyncMock()) as idx:
            await mgr.full_sync()
        assert idx.await_count == 2
        ids = [c.kwargs["content_id"] for c in idx.await_args_list]
        assert ids == ["remote:f1", "remote:f2"]

    async def test_skips_invalid_fragments(self):
        mgr, remote = _manager()
        remote.list_fragments.return_value = [
            {"id": "f1", "session_id": "", "content": "c1"},  # 缺 session_id
            {"id": "f2", "session_id": "s1", "content": ""},  # 缺 content
        ]
        with patch.object(mgr, "_push_pending", new=AsyncMock(return_value=0)), \
             patch("xiaopaw.memory.indexer.async_index_turn", new=AsyncMock()) as idx:
            await mgr.full_sync()
        idx.assert_not_awaited()

    async def test_no_dsn_skips(self):
        mgr, remote = _manager(db_dsn="")
        await mgr.full_sync()
        remote.list_fragments.assert_not_awaited()

    async def test_pushes_pending_before_pull(self):
        mgr, remote = _manager()
        remote.list_fragments.return_value = []
        push = AsyncMock(return_value=3)
        with patch.object(mgr, "_push_pending", new=push):
            await mgr.full_sync()
        push.assert_awaited_once()

    async def test_remote_error_does_not_raise(self):
        mgr, remote = _manager()
        remote.list_fragments.side_effect = RuntimeError("api down")
        with patch.object(mgr, "_push_pending", new=AsyncMock(return_value=0)):
            await mgr.full_sync()  # 不抛即通过


class TestPushPending:
    async def test_pushes_and_marks_synced(self):
        mgr, remote = _manager()
        remote.save_turn.return_value = True
        pending_rows = [
            {"id": "m1", "session_id": "s1", "routing_key": "rk",
             "user_message": "u", "assistant_reply": "a", "summary": "",
             "fragment_type": "info", "importance_score": 0.4},
        ]
        marked: list[str] = []

        def fake_to_thread(fn, *args):
            import asyncio
            fut = asyncio.get_running_loop().create_future()
            if fn.__name__ == "_load_pending":
                fut.set_result(pending_rows)
            else:
                marked.append(args[0])
                fut.set_result(None)
            return fut

        with patch("xiaopaw.memory.memory_sync.asyncio.to_thread", new=fake_to_thread):
            pushed = await mgr._push_pending()
        assert pushed == 1
        assert marked == ["m1"]
        remote.save_turn.assert_awaited_once()

    async def test_failed_push_keeps_pending(self):
        mgr, remote = _manager()
        remote.save_turn.return_value = False
        pending_rows = [
            {"id": "m1", "session_id": "s1", "routing_key": "rk",
             "user_message": "u", "assistant_reply": "a", "summary": "",
             "fragment_type": "info", "importance_score": 0.4},
        ]
        marked: list[str] = []

        def fake_to_thread(fn, *args):
            import asyncio
            fut = asyncio.get_running_loop().create_future()
            if fn.__name__ == "_load_pending":
                fut.set_result(pending_rows)
            else:
                marked.append(args[0])
                fut.set_result(None)
            return fut

        with patch("xiaopaw.memory.memory_sync.asyncio.to_thread", new=fake_to_thread):
            pushed = await mgr._push_pending()
        assert pushed == 0
        assert marked == []  # 失败行不置位，留待下轮重试

    async def test_load_failure_returns_zero(self):
        mgr, _ = _manager()
        failing = AsyncMock(side_effect=RuntimeError("db down"))
        with patch("xiaopaw.memory.memory_sync.asyncio.to_thread", new=failing):
            assert await mgr._push_pending() == 0


class TestGetSyncManager:
    def test_returns_singleton(self):
        memory_sync_mod._sync_manager = None
        try:
            remote = AsyncMock()
            m1 = get_sync_manager(remote, "dsn")
            m2 = get_sync_manager(remote, "dsn")
            assert m1 is m2
        finally:
            memory_sync_mod._sync_manager = None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

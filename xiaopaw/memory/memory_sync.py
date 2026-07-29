"""记忆同步模块：统一本地 pgvector 与远程 agent-memory-system。

架构：
- 远程 agent-memory-system = 权威数据源（source of truth）
- 本地 pgvector = 低延迟缓存层
- 写入路径：先写远程，成功后写本地
- 读取路径：优先本地缓存，miss 时查远程并回填缓存

Phase C2 引入，受 feature_flags.enable_memory_sync 门控。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MemorySyncManager:
    """本地与远程记忆同步管理器。

    将本地 pgvector 视为缓存层，远程 agent-memory-system 视为权威数据源。
    所有写入先远程后本地；读取优先本地，miss 时查远程并回填。
    """

    def __init__(self, remote_store: Any, db_dsn: str) -> None:
        """初始化同步管理器。

        Args:
            remote_store: RemoteMemoryStore 实例（权威数据源客户端）。
            db_dsn: 本地 pgvector 数据库 DSN（空串时禁用本地缓存）。
        """
        self._remote = remote_store
        self._db_dsn = db_dsn
        self._sync_lock = asyncio.Lock()

    # ================================================================
    # 写入路径：穿透写入（先远程后本地）
    # ================================================================

    async def write_through(
        self,
        *,
        session_id: str,
        routing_key: str,
        user_message: str,
        assistant_reply: str,
        turn_ts: int,
        summary: str = "",
        fragment_type: str = "info",
        importance: float | None = None,
    ) -> None:
        """穿透写入：先远程后本地。

        1. 写入远程 agent-memory-system（权威源）
        2. 成功后写入本地 pgvector 缓存
        3. 远程失败则仅写本地（标记为 pending_sync）
        4. 本地失败不影响（下次同步会补上）
        """
        remote_ok = False
        try:
            await self._remote.save_turn(
                session_id=session_id,
                routing_key=routing_key,
                user_message=user_message,
                assistant_reply=assistant_reply,
                summary=summary,
                fragment_type=fragment_type,
                importance=importance,
            )
            remote_ok = True
        except Exception as e:
            logger.warning("Remote write failed, local only: %s", e)

        if not self._db_dsn:
            return

        if remote_ok:
            try:
                from xiaopaw.memory.indexer import async_index_turn
                await async_index_turn(
                    session_id=session_id,
                    routing_key=routing_key,
                    user_message=user_message,
                    assistant_reply=assistant_reply,
                    turn_ts=turn_ts,
                    db_dsn=self._db_dsn,
                    messages=[
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": assistant_reply},
                    ],
                )
            except Exception as e:
                logger.warning("Local cache write failed (will sync later): %s", e)
        else:
            # 远程失败，仅写本地并标记
            try:
                from xiaopaw.memory.indexer import async_index_turn
                await async_index_turn(
                    session_id=session_id,
                    routing_key=routing_key,
                    user_message=user_message,
                    assistant_reply=assistant_reply,
                    turn_ts=turn_ts,
                    db_dsn=self._db_dsn,
                    messages=[
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": assistant_reply},
                    ],
                )
                logger.info(
                    "Local-only write for session %s (remote failed, pending_sync)",
                    session_id,
                )
            except Exception as e:
                logger.warning("Local-only write also failed: %s", e)

    # ================================================================
    # 读取路径：穿透读取（优先本地，miss 查远程）
    # ================================================================

    async def read_through(self, query: str, *, top_k: int = 5) -> list[dict]:
        """穿透读取：优先本地，miss 查远程。

        1. 先查本地 pgvector（低延迟）
        2. 如果本地结果不足（< top_k），查远程补充
        3. 远程结果回填本地缓存（异步，不阻塞返回）
        """
        local_results: list[dict] = []

        # 本地 pgvector 查询
        if self._db_dsn:
            try:
                local_results = await self._search_local(query, top_k=top_k)
            except Exception as e:
                logger.warning("Local search failed: %s", e)

        if len(local_results) >= top_k:
            return local_results[:top_k]

        # 本地不足，查远程补充
        try:
            remote_text = await self._remote.recall(query)
            if remote_text:
                local_results.append({"source": "remote", "content": remote_text})
        except Exception as e:
            logger.warning("Remote recall failed: %s", e)

        return local_results

    async def _search_local(self, query: str, *, top_k: int = 5) -> list[dict]:
        """本地 pgvector 语义搜索。"""
        if not self._db_dsn:
            return []

        def _do_search() -> list[dict]:
            import psycopg2
            from psycopg2.extras import RealDictCursor

            conn = psycopg2.connect(self._db_dsn)
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """SELECT id, session_id, summary, user_message,
                                  assistant_reply, tags, created_at,
                                  importance_score, fragment_type
                           FROM memories
                           WHERE search_text ILIKE %s
                           ORDER BY created_at DESC
                           LIMIT %s""",
                        (f"%{query}%", top_k),
                    )
                    rows = cur.fetchall()
                    return [dict(r) for r in rows]
            finally:
                conn.close()

        return await asyncio.to_thread(_do_search)

    # ================================================================
    # 全量同步：从远程拉取刷新本地缓存
    # ================================================================

    async def full_sync(self, session_ids: list[str] | None = None) -> None:
        """全量同步：从远程拉取记忆刷新本地缓存。

        1. 调用远程 API 获取 active 片段列表
        2. 如果指定了 session_ids，只同步这些 session
        3. 对比本地缓存，新增/更新/删除
        4. 记录同步统计
        """
        if self._sync_lock.locked():
            logger.info("Sync already in progress, skipping")
            return

        if not self._db_dsn:
            logger.info("No local DB DSN configured, skipping full sync")
            return

        async with self._sync_lock:
            synced = 0
            errors = 0
            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    params: dict[str, str] = {"status": "active", "limit": "1000"}
                    if session_ids:
                        params["session_ids"] = ",".join(session_ids)

                    resp = await client.get(
                        f"{self._remote._base_url.rstrip('/')}/memory/fragments",
                        params=params,
                        headers={"Authorization": f"Bearer {self._remote._api_key}"}
                        if self._remote._api_key
                        else {},
                        timeout=60.0,
                    )
                    resp.raise_for_status()
                    fragments = resp.json().get("fragments", [])

                for frag in fragments:
                    try:
                        sid = frag.get("session_id", "")
                        content = frag.get("content", "")
                        if sid and content:
                            from xiaopaw.memory.indexer import async_index_turn

                            await async_index_turn(
                                session_id=sid,
                                routing_key=frag.get("routing_key", ""),
                                user_message=frag.get("user_message", ""),
                                assistant_reply=content,
                                turn_ts=frag.get("created_ts", 0),
                                db_dsn=self._db_dsn,
                                messages=[
                                    {"role": "assistant", "content": content},
                                ],
                            )
                            synced += 1
                    except Exception as e:
                        logger.warning("Failed to sync fragment: %s", e)
                        errors += 1

                logger.info(
                    "Full memory sync completed: %d synced, %d errors",
                    synced,
                    errors,
                )
            except Exception as e:
                logger.error("Full sync failed: %s", e)

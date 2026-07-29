"""记忆同步模块：统一本地 pgvector 与远程 agent-memory-system。

架构：
- 远程 agent-memory-system = 权威数据源（source of truth）
- 本地 pgvector = 低延迟缓存层
- 写入路径：先写远程，成功后写本地；远程失败时本地行标记
  remote_synced=FALSE（pending），由 full_sync 补偿推送
- 读取路径：优先本地缓存，不足时查远程补充

Phase C2 引入，受 feature_flags.enable_memory_sync 门控。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 进程级单例缓存（get_sync_manager 惰性创建），保证 full_sync
# 的 _sync_lock 在所有调用方间真正互斥
_sync_manager: MemorySyncManager | None = None


def get_sync_manager(remote_store: Any, db_dsn: str) -> MemorySyncManager:
    """返回进程级 MemorySyncManager 单例（首次调用时创建）。"""
    global _sync_manager
    if _sync_manager is None:
        _sync_manager = MemorySyncManager(remote_store, db_dsn)
    return _sync_manager


def _escape_like(text: str) -> str:
    """转义 LIKE/ILIKE 模式中的通配符，避免用户输入改变匹配语义。"""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class MemorySyncManager:
    """本地与远程记忆同步管理器。

    将本地 pgvector 视为缓存层，远程 agent-memory-system 视为权威数据源。
    所有写入先远程后本地；读取优先本地，不足时查远程补充。

    注意：full_sync 的并发互斥依赖同一实例的 _sync_lock，
    调用方应复用进程级单例而非每次新建。
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

        1. 写入远程 agent-memory-system（权威源），以 save_turn 返回值判定成败
        2. 无论远程成败均写本地缓存；远程失败的行标记 remote_synced=FALSE
        3. 本地失败不影响远程结果（full_sync 会从远程回填）
        """
        try:
            remote_ok = bool(
                await self._remote.save_turn(
                    session_id=session_id,
                    routing_key=routing_key,
                    user_message=user_message,
                    assistant_reply=assistant_reply,
                    summary=summary,
                    fragment_type=fragment_type,
                    importance=importance,
                )
            )
        except Exception as e:
            # save_turn 自身不抛异常，此处兜底防御接口变更
            logger.warning("Remote write failed, local only: %s", e)
            remote_ok = False

        if not self._db_dsn:
            if not remote_ok:
                logger.error(
                    "write_through lost turn for session %s: remote failed "
                    "and no local cache configured", session_id,
                )
            return

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
                remote_synced=remote_ok,
                fragment_type=fragment_type,
            )
            if not remote_ok:
                logger.info(
                    "Local-only write for session %s (remote failed, pending sync)",
                    session_id,
                )
        except Exception as e:
            if remote_ok:
                logger.warning("Local cache write failed (will sync later): %s", e)
            else:
                logger.error(
                    "write_through lost turn for session %s: both remote and "
                    "local writes failed: %s", session_id, e,
                )

    # ================================================================
    # 读取路径：穿透读取（优先本地，不足查远程）
    # ================================================================

    async def read_through(self, query: str, *, top_k: int = 5) -> list[dict]:
        """穿透读取：优先本地，不足查远程。

        1. 先查本地 pgvector（低延迟），结果带 source="local"
        2. 如果本地结果不足（< top_k），查远程补充（source="remote"）
        3. 本地与远程均失败时返回空列表，不向上抛
        """
        local_results: list[dict] = []

        # 本地 pgvector 查询
        if self._db_dsn:
            try:
                local_results = await self._search_local(query, top_k=top_k)
            except Exception as e:
                logger.warning("Local search failed: %s", e)

        for r in local_results:
            r.setdefault("source", "local")

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
        """本地 pgvector 文本检索（search_text 子串匹配）。"""
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
                        (f"%{_escape_like(query)}%", top_k),
                    )
                    rows = cur.fetchall()
                    return [dict(r) for r in rows]
            finally:
                conn.close()

        return await asyncio.to_thread(_do_search)

    # ================================================================
    # 全量同步：双向 —— 先补偿推送 pending 行，再从远程拉取回填
    # ================================================================

    async def full_sync(self, session_ids: list[str] | None = None) -> None:
        """全量同步（增量合并语义，不删除本地行）。

        1. 补偿推送：本地 remote_synced=FALSE 的行重推远程，成功后置回 TRUE
        2. 从远程拉取 active 片段（可按 session_ids 过滤），以片段 id 为
           主键回填本地缓存（已存在则跳过，避免重复 LLM/embedding 调用）
        3. 记录同步统计
        """
        if not self._db_dsn:
            logger.info("No local DB DSN configured, skipping full sync")
            return

        if self._sync_lock.locked():
            logger.info("Sync already in progress, skipping")
            return

        async with self._sync_lock:
            pushed = await self._push_pending()
            synced = 0
            errors = 0
            try:
                fragments = await self._remote.list_fragments(
                    status="active", session_ids=session_ids, limit=1000,
                )
                for frag in fragments:
                    try:
                        sid = frag.get("session_id", "")
                        content = frag.get("content", "")
                        frag_id = str(frag.get("id", "")).strip()
                        if not (sid and content):
                            continue
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
                            # 远程片段 id 作为本地主键，避免 created_ts
                            # 缺省 0 时同 session 多片段 hash 碰撞互相覆盖
                            content_id=f"remote:{frag_id}" if frag_id else None,
                            fragment_type=frag.get("fragment_type", frag.get("type", "info")),
                        )
                        synced += 1
                    except Exception as e:
                        logger.warning("Failed to sync fragment: %s", e)
                        errors += 1

                logger.info(
                    "Full memory sync completed: %d pushed, %d pulled, %d errors",
                    pushed,
                    synced,
                    errors,
                )
            except Exception as e:
                logger.error("Full sync failed: %s", e)

    async def _push_pending(self) -> int:
        """把本地 remote_synced=FALSE 的行补偿推送到远程权威源。

        推送成功后置回 TRUE；单行失败不中断，留待下轮同步重试。
        Returns: 成功推送条数。
        """

        def _load_pending() -> list[dict]:
            import psycopg2
            from psycopg2.extras import RealDictCursor

            conn = psycopg2.connect(self._db_dsn)
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """SELECT id, session_id, routing_key, user_message,
                                  assistant_reply, summary, fragment_type,
                                  importance_score
                           FROM memories
                           WHERE remote_synced = FALSE
                           ORDER BY created_at
                           LIMIT 500""",
                    )
                    return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        def _mark_synced(row_id: str) -> None:
            import psycopg2

            conn = psycopg2.connect(self._db_dsn)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE memories SET remote_synced = TRUE WHERE id = %s",
                        (row_id,),
                    )
                conn.commit()
            finally:
                conn.close()

        pushed = 0
        try:
            pending = await asyncio.to_thread(_load_pending)
        except Exception as e:
            logger.warning("Failed to load pending rows: %s", e)
            return 0

        for row in pending:
            try:
                ok = bool(
                    await self._remote.save_turn(
                        session_id=row["session_id"],
                        routing_key=row.get("routing_key", ""),
                        user_message=row.get("user_message", ""),
                        assistant_reply=row.get("assistant_reply", ""),
                        summary=row.get("summary", "") or "",
                        fragment_type=row.get("fragment_type") or "info",
                        importance=row.get("importance_score"),
                    )
                )
                if ok:
                    await asyncio.to_thread(_mark_synced, row["id"])
                    pushed += 1
            except Exception as e:
                logger.warning("Failed to push pending row %s: %s", row.get("id"), e)

        if pending:
            logger.info("Pushed %d/%d pending rows to remote", pushed, len(pending))
        return pushed

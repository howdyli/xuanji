"""Remote long-term memory store backed by agent-memory-system (via SDK).

对接 pm/agent-memory-system 的 HTTP 后端，通过 agent-memory-sdk 的
AsyncMemoryClient 提供两个 fire-and-forget 安全能力：

- ``save_turn``：每轮对话后把摘要/原文写为记忆片段（fragment）
- ``recall``：推理前用当前用户消息召回长期记忆上下文

设计原则（与 llm/model_router.py 的进程级单例一致）：
- 模块级单例 ``remote_memory_store``，main.py 启动时 ``init_from_config``
- SDK 为可选依赖（pyproject [remote-memory]），未安装时静默降级为禁用
- 所有方法内部吞异常并记日志：记忆服务故障绝不阻断对话主流程
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# 单 workspace 策略：routing_key 写入 fragment metadata 做用户维度区分。
# 后续演进为 per-routing_key workspace 时，只需改这一个文件的映射逻辑。
_FRAGMENT_SOURCE = "xiaopaw"

# FR-3 启发式 importance 打分：命中显式陈述/偏好模式→高分片段
_IMPORTANT_PATTERN = re.compile(r"记住|我是|我的|以后|我喜欢|我不喜欢|叫我|别忘了")

# FR-6 每 N 次读写操作输出一行计数汇总日志
_STATS_LOG_EVERY = 100


class RemoteMemoryStore:
    """agent-memory-system 异步客户端封装（进程级单例使用）。"""

    def __init__(self) -> None:
        self._base_url = ""
        self._api_key = ""
        self._timeout = 10.0
        self._recall_top_k = 5
        self._recall_max_chars = 4000
        self._max_save_length = 2000
        self._fragment_ttl_days = 90
        self._importance_default = 0.4
        self._importance_high = 0.7
        self._summary_timeout = 5.0
        # Phase 5 结构化记忆表：白名单 schema + 建表结果进程内缓存
        self._structured_tables: dict[str, list[dict[str, str]]] = {}
        self._ensured_tables: set[str] = set()
        self._enabled = False
        self._client: Any | None = None
        # save_turn 的后台任务引用，防止被 GC 提前取消
        self._pending_tasks: set[asyncio.Task] = set()
        # FR-6 可观测性计数器（进程内累加，stats() 暴露）
        self._stats = {
            "recall_total": 0,
            "recall_hit": 0,
            "save_total": 0,
            "save_failed": 0,
            # Phase 5 FR-5：结构化表写入计数
            "table_write_total": 0,
            "table_write_failed": 0,
        }

    # ================================================================
    # 配置
    # ================================================================

    def init_from_config(self, memory_cfg: Any, flags: Any) -> None:
        """从 AppConfig.memory + feature_flags 初始化。main.py 启动时调用。

        flag 关闭或 remote_base_url/remote_api_key 缺失时保持禁用，
        所有读写方法直接短路返回 —— 与现状行为完全一致。
        """
        if not getattr(flags, "enable_remote_memory", False):
            logger.info("remote memory disabled (feature flag off)")
            return
        base_url = (getattr(memory_cfg, "remote_base_url", "") or "").strip()
        api_key = (getattr(memory_cfg, "remote_api_key", "") or "").strip()
        if not base_url or not api_key:
            logger.warning(
                "remote memory flag is ON but memory.remote_base_url/remote_api_key "
                "is empty — remote memory stays disabled",
            )
            return
        if "/api/" not in base_url:
            logger.warning(
                "memory.remote_base_url (%s) looks like it is missing the /api/v1 "
                "prefix; requests will likely 404", base_url,
            )
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = float(getattr(memory_cfg, "remote_timeout", 10.0))
        self._recall_top_k = int(getattr(memory_cfg, "recall_top_k", 5))
        self._recall_max_chars = int(getattr(memory_cfg, "recall_max_chars", 4000))
        self._max_save_length = int(getattr(memory_cfg, "max_save_length", 2000))
        self._fragment_ttl_days = int(getattr(memory_cfg, "fragment_ttl_days", 90))
        self._importance_default = float(getattr(memory_cfg, "importance_default", 0.4))
        self._importance_high = float(getattr(memory_cfg, "importance_high", 0.7))
        self._summary_timeout = float(getattr(memory_cfg, "summary_timeout", 5.0))
        self._structured_tables = dict(getattr(memory_cfg, "structured_tables", {}) or {})
        self._enabled = True
        logger.info("remote memory enabled: %s", base_url)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # ================================================================
    # FR-6 可观测性
    # ================================================================

    def _bump(self, counter: str) -> None:
        """累加计数器；每 _STATS_LOG_EVERY 次读写操作输出一行汇总日志。"""
        self._stats[counter] += 1
        ops = self._stats["recall_total"] + self._stats["save_total"]
        if ops and ops % _STATS_LOG_EVERY == 0:
            logger.info(
                "remote memory stats: recall %d/%d hit, save %d total / %d failed, "
                "table write %d total / %d failed",
                self._stats["recall_hit"], self._stats["recall_total"],
                self._stats["save_total"], self._stats["save_failed"],
                self._stats["table_write_total"], self._stats["table_write_failed"],
            )

    def stats(self) -> dict:
        """四项计数 + 待完成后台任务数，供健康检查端点暴露。"""
        return {**self._stats, "pending_tasks": len(self._pending_tasks)}

    def _get_client(self) -> Any | None:
        """懒初始化 AsyncMemoryClient（复用 httpx 连接池）。

        SDK 未安装时降级为禁用并告警一次，不抛异常。
        """
        if not self._enabled:
            return None
        if self._client is None:
            try:
                from agent_memory.async_client import AsyncMemoryClient
            except ImportError:
                logger.warning(
                    "agent-memory-sdk not installed, remote memory disabled. "
                    "Install via: pip install -e ../pm/agent-memory-system/sdk-python",
                )
                self._enabled = False
                return None
            self._client = AsyncMemoryClient(
                base_url=self._base_url,
                api_key=self._api_key,
                timeout=self._timeout,
            )
        return self._client

    # ================================================================
    # 召回（读路径）
    # ================================================================

    async def recall(self, query: str, routing_key: str = "", top_k: int | None = None) -> str:
        """用 query 召回长期记忆上下文。失败/超时/空结果一律返回空串。"""
        client = self._get_client()
        if client is None or not query.strip():
            return ""
        self._bump("recall_total")
        try:
            context = await asyncio.wait_for(
                client.recall_context(query, top_k=top_k or self._recall_top_k),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("remote memory recall timed out (%.1fs)", self._timeout)
            return ""
        except Exception as exc:
            logger.warning("remote memory recall failed: %s", exc)
            return ""
        if not context:
            return ""
        self._bump("recall_hit")
        if len(context) > self._recall_max_chars:
            marker = "...(截断)"
            return context[: self._recall_max_chars - len(marker)] + marker
        return context

    # ================================================================
    # 写入（写路径，fire-and-forget）
    # ================================================================

    def _score_importance(self, user_message: str) -> float:
        """FR-3 启发式打分：含显式陈述/偏好模式的消息→高分。"""
        if _IMPORTANT_PATTERN.search(user_message):
            return self._importance_high
        return self._importance_default

    async def _summarize_turn(self, user_message: str, assistant_reply: str) -> str:
        """FR-4 用廉价模型生成 ≤100 字一句话摘要；失败/超时返回空串。

        同步 LLM 调用放入线程池，不阻塞事件循环；本方法只在
        save_turn 后台任务内被调用，不增加回复延迟。
        """
        try:
            from xiaopaw.llm.model_router import model_router

            if not model_router._models:
                return ""
            llm = model_router.get_llm(task_type="memory_indexing")
            prompt = (
                "用一句中文（≤100字）概括以下对话的核心信息，保留关键实体，"
                "直接输出摘要正文：\n"
                f"用户：{user_message[:500]}\n助手：{assistant_reply[:1000]}"
            )
            summary = await asyncio.wait_for(
                asyncio.to_thread(llm.call, prompt),
                timeout=self._summary_timeout,
            )
            return str(summary or "").strip()[:100]
        except asyncio.TimeoutError:
            logger.warning(
                "remote memory summarize timed out (%.1fs), falling back to raw",
                self._summary_timeout,
            )
            return ""
        except Exception as exc:
            logger.warning("remote memory summarize failed: %s", exc)
            return ""

    async def save_turn(
        self,
        session_id: str,
        routing_key: str,
        user_message: str,
        assistant_reply: str,
        summary: str = "",
    ) -> None:
        """把一轮对话写为记忆片段。任何失败只记日志，不向上抛。"""
        client = self._get_client()
        if client is None:
            return
        # FR-4 摘要优先级：调用方提供 > LLM 一句话摘要 > 原文拼接回退
        content = summary.strip() or await self._summarize_turn(user_message, assistant_reply) or (
            f"用户：{user_message[:500]}\n助手：{assistant_reply[:1000]}"
        )
        # FR-3 生命周期：TTL（秒，0 天 = 永久→None）+ 启发式 importance
        ttl_seconds = self._fragment_ttl_days * 86400 or None
        self._bump("save_total")
        try:
            await asyncio.wait_for(
                client.remember_fragment(
                    content=content[: self._max_save_length],
                    fragment_type="info",
                    importance_score=self._score_importance(user_message),
                    ttl=ttl_seconds,
                    metadata={
                        "session_id": session_id,
                        "routing_key": routing_key,
                        "turn_ts": int(time.time() * 1000),
                        "source": _FRAGMENT_SOURCE,
                    },
                ),
                timeout=self._timeout,
            )
            logger.info("remote memory saved turn for session %s", session_id)
        except asyncio.TimeoutError:
            self._bump("save_failed")
            logger.warning("remote memory save_turn timed out (%.1fs)", self._timeout)
        except Exception as exc:
            self._bump("save_failed")
            logger.warning("remote memory save_turn failed: %s", exc)

    def save_turn_background(
        self,
        session_id: str,
        routing_key: str,
        user_message: str,
        assistant_reply: str,
        summary: str = "",
    ) -> None:
        """在事件循环上调度 save_turn 后台任务（不阻塞回复发送）。"""
        if not self._enabled:
            return
        try:
            task = asyncio.get_running_loop().create_task(
                self.save_turn(
                    session_id=session_id,
                    routing_key=routing_key,
                    user_message=user_message,
                    assistant_reply=assistant_reply,
                    summary=summary,
                )
            )
        except RuntimeError:
            # 无运行中的事件循环（如同步测试环境）：跳过而非崩溃
            logger.debug("save_turn_background skipped: no running event loop")
            return
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    # ================================================================
    # FR-1 用户偏好（Variables，upsert 语义）
    # ================================================================

    async def set_preference(
        self, key: str, value: Any, scope: str = "user", routing_key: str = ""
    ) -> bool:
        """写入/覆盖一条用户偏好（Variables upsert）。失败返回 False 不抛。"""
        client = self._get_client()
        if client is None or not key.strip():
            return False
        try:
            return bool(
                await asyncio.wait_for(
                    client.remember(key.strip(), value), timeout=self._timeout
                )
            )
        except Exception as exc:
            logger.warning("remote memory set_preference(%s) failed: %s", key, exc)
            return False

    async def get_preferences(self, routing_key: str = "") -> dict:
        """读取全部用户偏好键值。失败返回空 dict。

        注入上限 20 条：超限时保留最近创建的 20 条（后端索引按创建
        顺序追加，取尾部即最新）。
        """
        client = self._get_client()
        if client is None:
            return {}
        try:
            variables = await asyncio.wait_for(
                client.list_variables(), timeout=self._timeout
            )
        except Exception as exc:
            logger.warning("remote memory get_preferences failed: %s", exc)
            return {}
        if not isinstance(variables, dict):
            return {}
        if len(variables) > 20:
            variables = dict(list(variables.items())[-20:])
        return variables

    def set_preference_sync(self, key: str, value: Any) -> bool:
        """同步写入偏好，供 CrewAI 工具线程使用。

        工具 _run 跑在 executor 线程里（无事件循环，也不能跨循环
        复用 _client 的 httpx.AsyncClient），故用一次性同步请求。
        """
        if not self._enabled or not key.strip():
            return False
        try:
            import httpx

            resp = httpx.post(
                f"{self._base_url.rstrip('/')}/memory/variables",
                json={"key": key.strip(), "value": value, "ttl": None},
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
            return resp.status_code < 400
        except Exception as exc:
            logger.warning("remote memory set_preference_sync(%s) failed: %s", key, exc)
            return False

    # ================================================================
    # Phase 5 结构化记忆表（Tables，白名单 + 懒建表）
    #
    # 全部为同步方法：调用方是 CrewAI 工具的 _run（executor 线程，
    # 无事件循环，不能跨循环复用 _client），与 set_preference_sync 同约束。
    # ================================================================

    def table_schema(self, table_name: str) -> list[dict[str, str]] | None:
        """返回白名单表的字段 schema；白名单外返回 None。"""
        return self._structured_tables.get(table_name)

    @property
    def allowed_tables(self) -> list[str]:
        return sorted(self._structured_tables)

    def _table_request_sync(self, method: str, path: str, **kwargs: Any) -> Any | None:
        """一次性同步 HTTP 请求；失败返回 None 并记日志，不抛。"""
        try:
            import httpx

            resp = httpx.request(
                method,
                f"{self._base_url.rstrip('/')}{path}",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
                **kwargs,
            )
        except Exception as exc:
            logger.warning("remote memory table request %s %s failed: %s", method, path, exc)
            return None
        return resp

    def ensure_table_sync(self, table_name: str) -> bool:
        """首次写入前确保表存在（幂等）。白名单外直接 False。

        服务端已存在视为成功；成功结果进程内缓存，同表只探测一次。
        """
        if not self._enabled:
            return False
        fields = self._structured_tables.get(table_name)
        if fields is None:
            return False
        if table_name in self._ensured_tables:
            return True
        resp = self._table_request_sync(
            "POST", "/memory/tables",
            json={"table_name": table_name, "fields": fields},
        )
        if resp is None:
            return False
        if resp.status_code < 400 or "exist" in resp.text.lower():
            self._ensured_tables.add(table_name)
            return True
        logger.warning(
            "remote memory ensure_table(%s) failed: HTTP %d %s",
            table_name, resp.status_code, resp.text[:200],
        )
        return False

    def add_record_sync(self, table_name: str, record: dict) -> int | None:
        """插入一条记录，返回新记录 ID；失败返回 None。"""
        if not self.ensure_table_sync(table_name):
            return None
        self._bump("table_write_total")
        resp = self._table_request_sync(
            "POST", f"/memory/tables/{table_name}/records", json={"record": record},
        )
        if resp is None or resp.status_code >= 400:
            self._bump("table_write_failed")
            return None
        try:
            data = resp.json()
            return data.get("record_id", data.get("id"))
        except Exception:
            return None

    def update_record_sync(self, table_name: str, record_id: int, updates: dict) -> bool:
        """按 record_id 更新既有记录。失败返回 False。"""
        if not self.ensure_table_sync(table_name):
            return False
        self._bump("table_write_total")
        resp = self._table_request_sync(
            "PUT", f"/memory/tables/{table_name}/records",
            json={"updates": updates}, params={"record_id": record_id},
        )
        if resp is None or resp.status_code >= 400:
            self._bump("table_write_failed")
            return False
        return True

    def query_records_sync(
        self, table_name: str, filters: dict | None = None, limit: int = 20
    ) -> list[dict] | None:
        """查询记录（等值过滤）。白名单外/失败返回 None，无命中返回 []。"""
        if not self._enabled or table_name not in self._structured_tables:
            return None
        resp = self._table_request_sync(
            "POST", f"/memory/tables/{table_name}/query",
            json={"filters": filters or None, "limit": limit},
        )
        if resp is None or resp.status_code >= 400:
            return None
        try:
            return resp.json().get("records", [])
        except Exception:
            return None

    # ================================================================
    # 生命周期
    # ================================================================

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None


# 进程级单例（与 model_router 同模式）
remote_memory_store = RemoteMemoryStore()

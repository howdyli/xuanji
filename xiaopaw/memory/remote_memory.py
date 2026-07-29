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
            # Phase A：extraction + lifecycle 计数
            "extraction_total": 0,
            "extraction_failed": 0,
            "lifecycle_total": 0,
            "lifecycle_failed": 0,
            "conflict_total": 0,
            "conflict_failed": 0,
            # Phase B1：三层召回计数
            "recall_layered_total": 0,
            "recall_layered_failed": 0,
            "recall_layered_fallback": 0,
            # Phase C1：图谱记忆计数
            "graph_query_total": 0,
            "graph_query_failed": 0,
            "graph_ingest_total": 0,
            "graph_ingest_failed": 0,
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
                "table write %d total / %d failed, layered recall %d total / %d failed / %d fallback, "
                "graph query %d total / %d failed, graph ingest %d total / %d failed",
                self._stats["recall_hit"], self._stats["recall_total"],
                self._stats["save_total"], self._stats["save_failed"],
                self._stats["table_write_total"], self._stats["table_write_failed"],
                self._stats["recall_layered_total"], self._stats["recall_layered_failed"],
                self._stats["recall_layered_fallback"],
                self._stats["graph_query_total"], self._stats["graph_query_failed"],
                self._stats["graph_ingest_total"], self._stats["graph_ingest_failed"],
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
    # Phase B1: 三层分层召回（recall.auto）
    # ================================================================

    async def recall_layered(self, query: str, *, token_budget: int = 4000) -> dict:
        """调用 agent-memory-system 的三层召回 API。

        1. 调用 POST {base_url}/memory/recall/auto
           body: {"query": query, "token_budget": token_budget,
                  "layers": ["profile", "semantic", "entity_expansion"]}
        2. 解析返回结构：
           {
               "profile": str,           # Level 1: KV 变量 + 高重要性片段
               "semantic": str,          # Level 2: 语义记忆
               "entity_expansion": str,  # Level 3: 实体展开
               "total_tokens": int,
           }
        3. 如果 API 不可用或失败，降级到现有 recall() 方法。

        超时 15s，失败静默降级。
        """
        self._bump("recall_layered_total")
        fallback: dict = {
            "profile": "", "semantic": "", "entity_expansion": "", "total_tokens": 0,
        }

        if not self._enabled:
            # 未启用远程记忆，直接降级到普通 recall
            self._bump("recall_layered_fallback")
            plain = await self.recall(query)
            fallback["profile"] = plain
            fallback["total_tokens"] = len(plain) // 2
            return fallback

        try:
            import httpx

            async with httpx.AsyncClient() as _client:
                resp = await asyncio.wait_for(
                    _client.post(
                        f"{self._base_url.rstrip('/')}/memory/recall/auto",
                        json={
                            "query": query,
                            "token_budget": token_budget,
                            "layers": ["profile", "semantic", "entity_expansion"],
                        },
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        timeout=15.0,
                    ),
                    timeout=15.0,
                )
            if resp.status_code >= 400:
                logger.warning(
                    "recall_layered API returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
                self._bump("recall_layered_failed")
                return await self._fallback_layered_recall(query)

            data = resp.json()
            result = {
                "profile": data.get("profile", ""),
                "semantic": data.get("semantic", ""),
                "entity_expansion": data.get("entity_expansion", ""),
                "total_tokens": data.get("total_tokens", 0),
            }
            logger.info(
                "recall_layered success: tokens=%d, profile=%d chars, semantic=%d chars, entity=%d chars",
                result["total_tokens"],
                len(result["profile"]),
                len(result["semantic"]),
                len(result["entity_expansion"]),
            )
            return result

        except asyncio.TimeoutError:
            logger.warning("recall_layered API timed out (15s)")
            self._bump("recall_layered_failed")
            return await self._fallback_layered_recall(query)
        except Exception as exc:
            logger.warning("recall_layered API failed: %s", exc)
            self._bump("recall_layered_failed")
            return await self._fallback_layered_recall(query)

    async def _fallback_layered_recall(self, query: str) -> dict:
        """降级到普通 recall()，结果放入 profile 层。"""
        self._bump("recall_layered_fallback")
        plain = await self.recall(query)
        return {
            "profile": plain,
            "semantic": "",
            "entity_expansion": "",
            "total_tokens": len(plain) // 2,
        }

    # ================================================================
    # 写入（写路径，fire-and-forget）
    # ================================================================

    def _score_importance(self, user_message: str) -> float:
        """FR-3 启发式打分：含显式陈述/偏好模式的消息→高分。"""
        if _IMPORTANT_PATTERN.search(user_message):
            return self._importance_high
        return self._importance_default

    # ================================================================
    # Phase B2: 多因子重要性评分（纯本地计算，不调 API）
    # ================================================================

    # 关键词 → 基础分 映射（5 档）
    _KW_EXPLICIT = re.compile(r"记住|别忘了|remember|必须记住|please remember", re.IGNORECASE)
    _KW_IDENTITY = re.compile(r"我是|我的名字|我喜欢|我不喜欢|叫我")
    _KW_WORK = re.compile(r"项目|工作|任务|deadline|进度")
    _KW_CHITCHAT = re.compile(r"^你好|^hi|^hello|^嗨|^谢谢|^thanks|^好的|^ok", re.IGNORECASE)
    _STRONG_EMOTION = re.compile(r"[!！]{2,}|非常|超级|极其|特别|绝对|一定|千万")
    _ENTITY_PERSON = re.compile(r"\b([A-Z][a-z]+)\b")  # 大写开头英文人名
    _ENTITY_ORG = re.compile(r"(公司|集团|学院|医院|大学|银行|机构|团队)")
    _ENTITY_LOCATION = re.compile(r"(市|区|省|路|街|大厦|国家)")
    _ENTITY_DATE = re.compile(r"\d{1,4}[年/-]\d{1,2}[月/-]\d{0,2}日?")

    def _score_importance_v2(self, text: str, msg_context: dict | None = None) -> float:
        """多因子重要性评分（0.0 ~ 1.0）。

        因子与权重：
        - 关键词匹配（0.30）：细分为 5 档
        - 用户显式标记（0.30）：包含"记住/别忘了/please remember" → 1.0，否则 0.3
        - 实体密度（0.20）：包含人名/组织/地点/日期 → min(density * 0.5, 1.0)
        - 消息长度（0.10）：len(text) > 200 → 0.8, > 100 → 0.5, > 50 → 0.3, else 0.1
        - 情感强度（0.10）：包含"!"或强烈情感词 → 0.8, 否则 0.3

        最终分数 = 各因子 * 权重 之和，clamp 到 [0.05, 0.95]
        """
        try:
            if not text or not text.strip():
                return 0.05

            # 1. 关键词匹配（0.30）
            if self._KW_EXPLICIT.search(text):
                kw_score = 0.9
            elif self._KW_IDENTITY.search(text):
                kw_score = 0.7
            elif self._KW_WORK.search(text):
                kw_score = 0.5
            elif self._KW_CHITCHAT.search(text):
                kw_score = 0.1
            else:
                kw_score = 0.3

            # 2. 用户显式标记（0.30）
            explicit_score = 1.0 if self._KW_EXPLICIT.search(text) else 0.3

            # 3. 实体密度（0.20）
            entity_count = 0
            if self._ENTITY_PERSON.search(text):
                entity_count += 1
            if self._ENTITY_ORG.search(text):
                entity_count += 1
            if self._ENTITY_LOCATION.search(text):
                entity_count += 1
            if self._ENTITY_DATE.search(text):
                entity_count += 1
            entity_score = min(entity_count * 0.5, 1.0)

            # 4. 消息长度（0.10）
            text_len = len(text)
            if text_len > 200:
                len_score = 0.8
            elif text_len > 100:
                len_score = 0.5
            elif text_len > 50:
                len_score = 0.3
            else:
                len_score = 0.1

            # 5. 情感强度（0.10）
            emotion_score = 0.8 if (self._STRONG_EMOTION.search(text) or "!" in text or "！" in text) else 0.3

            # 加权求和
            final = (
                0.30 * kw_score
                + 0.30 * explicit_score
                + 0.20 * entity_score
                + 0.10 * len_score
                + 0.10 * emotion_score
            )
            return max(0.05, min(0.95, final))

        except Exception as exc:
            logger.warning("_score_importance_v2 failed, using default: %s", exc)
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
        fragment_type: str = "info",
        importance: float | None = None,
    ) -> None:
        """把一轮对话写为记忆片段。任何失败只记日志，不向上抛。

        fragment_type: 记忆类型（info / preference / plan）。
        importance: 显式 importance 分；None 时使用启发式打分。
        """
        client = self._get_client()
        if client is None:
            return
        # FR-4 摘要优先级：调用方提供 > LLM 一句话摘要 > 原文拼接回退
        content = summary.strip() or await self._summarize_turn(user_message, assistant_reply) or (
            f"用户：{user_message[:500]}\n助手：{assistant_reply[:1000]}"
        )
        # FR-3 生命周期：TTL（秒，0 天 = 永久→None）+ 启发式 importance
        ttl_seconds = self._fragment_ttl_days * 86400 or None
        score = importance if importance is not None else self._score_importance(user_message)
        self._bump("save_total")
        try:
            await asyncio.wait_for(
                client.remember_fragment(
                    content=content[: self._max_save_length],
                    fragment_type=fragment_type,
                    importance_score=score,
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
            logger.info("remote memory saved turn for session %s (type=%s)", session_id, fragment_type)
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
        fragment_type: str = "info",
        importance: float | None = None,
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
                    fragment_type=fragment_type,
                    importance=importance,
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
    # Phase A1: Extraction API（LLM 驱动的结构化记忆抽取）
    # ================================================================

    async def extract_and_save(self, session_id: str, messages: list[dict]) -> dict:
        """调用 agent-memory-system 的 extraction API，从对话中抽取结构化记忆。

        流程：
        1. 调用 POST {base_url}/memory/extraction/extract
        2. 解析返回 {variables, facts, preferences, plans}
        3. 分类写入各类型记忆
        4. 返回统计 {extracted: N, saved: N, errors: [...]}

        超时 30s，失败不抛异常，log warning 后返回空统计。
        """
        if not self._enabled:
            return {"extracted": 0, "saved": 0, "errors": []}
        self._bump("extraction_total")
        empty: dict = {"extracted": 0, "saved": 0, "errors": []}
        try:
            import httpx

            async with httpx.AsyncClient() as _client:
                resp = await asyncio.wait_for(
                    _client.post(
                        f"{self._base_url.rstrip('/')}/memory/extraction/extract",
                        json={"session_id": session_id, "messages": messages},
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        timeout=30.0,
                    ),
                    timeout=30.0,
                )
            if resp.status_code >= 400:
                logger.warning(
                    "extraction API returned %d: %s", resp.status_code, resp.text[:200],
                )
                self._bump("extraction_failed")
                return empty
            data = resp.json()
        except asyncio.TimeoutError:
            logger.warning("extraction API timed out (30s)")
            self._bump("extraction_failed")
            return empty
        except Exception as exc:
            logger.warning("extraction API failed: %s", exc)
            self._bump("extraction_failed")
            return empty

        variables = data.get("variables", [])
        facts = data.get("facts", [])
        preferences = data.get("preferences", [])
        plans = data.get("plans", [])
        extracted = len(variables) + len(facts) + len(preferences) + len(plans)

        saved = 0
        errors: list[str] = []

        # variables → set_preference
        for v in variables:
            try:
                ok = await self.set_preference(v.get("key", ""), v.get("value", ""))
                if ok:
                    saved += 1
                else:
                    errors.append(f"variable {v.get('key', '?')}")
            except Exception as exc:
                errors.append(f"variable {v.get('key', '?')}: {exc}")

        # facts → remember_fragment(fragment_type="info")
        for text in facts:
            try:
                await self._save_fragment(str(text), "info")
                saved += 1
            except Exception as exc:
                errors.append(f"fact: {exc}")

        # preferences → remember_fragment(fragment_type="preference")
        for text in preferences:
            try:
                await self._save_fragment(str(text), "preference")
                saved += 1
            except Exception as exc:
                errors.append(f"preference: {exc}")

        # plans → remember_fragment(fragment_type="plan")
        for text in plans:
            try:
                await self._save_fragment(str(text), "plan")
                saved += 1
            except Exception as exc:
                errors.append(f"plan: {exc}")

        logger.info(
            "extraction complete for session %s: extracted=%d saved=%d errors=%d",
            session_id, extracted, saved, len(errors),
        )
        return {"extracted": extracted, "saved": saved, "errors": errors}

    async def _save_fragment(self, content: str, fragment_type: str) -> None:
        """内部辅助：写入单条语义记忆片段。"""
        client = self._get_client()
        if client is None:
            return
        await asyncio.wait_for(
            client.remember_fragment(
                content=content[: self._max_save_length],
                fragment_type=fragment_type,
                importance_score=self._importance_default,
            ),
            timeout=self._timeout,
        )

    # ================================================================
    # Phase A2: Lifecycle API（记忆生命周期管理）
    # ================================================================

    async def run_lifecycle_maintenance(self) -> dict:
        """调用生命周期维护 API。

        POST {base_url}/memory/lifecycle/maintenance
        返回 {marked_cold: N, soft_deleted: N, decayed: N}
        超时 60s，失败静默降级返回空统计。
        """
        empty = {"marked_cold": 0, "soft_deleted": 0, "decayed": 0}
        if not self._enabled:
            return empty
        self._bump("lifecycle_total")
        try:
            import httpx

            async with httpx.AsyncClient() as _client:
                resp = await asyncio.wait_for(
                    _client.post(
                        f"{self._base_url.rstrip('/')}/memory/lifecycle/maintenance",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        timeout=60.0,
                    ),
                    timeout=60.0,
                )
            if resp.status_code >= 400:
                logger.warning(
                    "lifecycle maintenance returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
                self._bump("lifecycle_failed")
                return empty
            return resp.json()
        except asyncio.TimeoutError:
            logger.warning("lifecycle maintenance timed out (60s)")
            self._bump("lifecycle_failed")
            return empty
        except Exception as exc:
            logger.warning("lifecycle maintenance failed: %s", exc)
            self._bump("lifecycle_failed")
            return empty

    async def detect_memory_conflicts(self) -> list[dict]:
        """调用冲突检测 API。

        POST {base_url}/memory/lifecycle/conflicts
        返回冲突对列表 [{id1, id2, reason}, ...]
        超时 30s，失败返回空列表。
        """
        if not self._enabled:
            return []
        self._bump("conflict_total")
        try:
            import httpx

            async with httpx.AsyncClient() as _client:
                resp = await asyncio.wait_for(
                    _client.post(
                        f"{self._base_url.rstrip('/')}/memory/lifecycle/conflicts",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        timeout=30.0,
                    ),
                    timeout=30.0,
                )
            if resp.status_code >= 400:
                logger.warning(
                    "conflict detection returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
                return []
            data = resp.json()
            return data.get("conflicts", [])
        except asyncio.TimeoutError:
            logger.warning("conflict detection timed out (30s)")
            return []
        except Exception as exc:
            logger.warning("conflict detection failed: %s", exc)
            return []

    # ================================================================
    # Phase C1: Graph Memory（实体-关系图谱查询与摄取）
    # ================================================================

    async def graph_query(self, entity: str, *, depth: int = 2) -> list[dict]:
        """查询实体关联图谱。

        1. 调用 GET {base_url}/memory/graph/query?entity={entity}&depth={depth}
        2. 返回 [{"entity": str, "relation": str, "target": str, "weight": float}, ...]
        3. 超时 10s，失败返回空列表
        4. 添加 _stats 计数：graph_query_total / graph_query_failed
        """
        if not self._enabled or not entity.strip():
            return []
        self._bump("graph_query_total")
        try:
            import httpx

            async with httpx.AsyncClient() as _client:
                resp = await asyncio.wait_for(
                    _client.get(
                        f"{self._base_url.rstrip('/')}/memory/graph/query",
                        params={"entity": entity.strip(), "depth": depth},
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        timeout=10.0,
                    ),
                    timeout=10.0,
                )
            if resp.status_code >= 400:
                logger.warning(
                    "graph_query API returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
                self._bump("graph_query_failed")
                return []
            data = resp.json()
            # 标准化返回格式
            neighbors = data.get("neighbors", data.get("results", []))
            return [
                {
                    "entity": n.get("entity_name", n.get("entity", "")),
                    "relation": n.get("relation_type", n.get("relation", "")),
                    "target": n.get("entity_name", n.get("target", "")),
                    "weight": float(n.get("confidence", n.get("weight", 0.5))),
                }
                for n in neighbors
            ]
        except asyncio.TimeoutError:
            logger.warning("graph_query API timed out (10s)")
            self._bump("graph_query_failed")
            return []
        except Exception as exc:
            logger.warning("graph_query API failed: %s", exc)
            self._bump("graph_query_failed")
            return []

    async def graph_ingest(self, text: str, *, session_id: str | None = None) -> dict:
        """从文本中抽取实体和关系，写入图谱。

        1. 调用 POST {base_url}/memory/graph/ingest
           body: {"text": text, "session_id": session_id}
        2. 返回 {"entities_extracted": N, "relations_created": N}
        3. 超时 15s，失败返回空统计
        4. 添加 _stats 计数：graph_ingest_total / graph_ingest_failed

        注意：这是 fire-and-forget 操作，调用方不需要等待结果。
        """
        empty = {"entities_extracted": 0, "relations_created": 0}
        if not self._enabled or not text.strip():
            return empty
        self._bump("graph_ingest_total")
        try:
            import httpx

            async with httpx.AsyncClient() as _client:
                resp = await asyncio.wait_for(
                    _client.post(
                        f"{self._base_url.rstrip('/')}/memory/graph/ingest",
                        json={"text": text, "session_id": session_id or ""},
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        timeout=15.0,
                    ),
                    timeout=15.0,
                )
            if resp.status_code >= 400:
                logger.warning(
                    "graph_ingest API returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
                self._bump("graph_ingest_failed")
                return empty
            data = resp.json()
            result = {
                "entities_extracted": data.get("entities_extracted", data.get("stored", {}).get("entities", 0)),
                "relations_created": data.get("relations_created", data.get("stored", {}).get("relationships", 0)),
            }
            logger.info(
                "graph_ingest success: entities=%d relations=%d",
                result["entities_extracted"], result["relations_created"],
            )
            return result
        except asyncio.TimeoutError:
            logger.warning("graph_ingest API timed out (15s)")
            self._bump("graph_ingest_failed")
            return empty
        except Exception as exc:
            logger.warning("graph_ingest API failed: %s", exc)
            self._bump("graph_ingest_failed")
            return empty

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

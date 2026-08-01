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

# P3 差异化 TTL 策略：按 fragment_type 设置不同半衰期
# info = 永久（TTL=None），plan = 90 天，preference = 180 天
_FRAGMENT_TTL_DAYS: dict[str, int | None] = {
    "info": None,          # 永久：事实性信息不过期
    "plan": 90,            # 计划类 90 天
    "preference": 180,     # 用户偏好 180 天（较持久）
}

# 分级错误处理：幂等读操作对 5xx/网络错误的指数退避间隔（秒）
_RETRY_BACKOFFS = (0.5, 1.0)

# 旧版 SDK（无公开 request()）回退私有传输层时，每进程只告警一次防刷屏。
_SDK_TRANSPORT_FALLBACK_WARNED = False

# 端点路径常量：统一维护，消除散落的字符串硬编码。
# SDK 高层方法未覆盖（recall/auto、fragments 分页、resilience、health）
# 或语义不满足的端点，经 httpx / SDK 传输层直连时引用。
_EP_HEALTH_LIVE = "/health/live"
_EP_RESILIENCE = "/system/llm/resilience"
_EP_RECALL_AUTO = "/memory/recall/auto"
_EP_HYBRID_SEARCH = "/memory/hybrid-search"
_EP_FRAGMENTS = "/memory/fragments"
_EP_LIFECYCLE_STATS = "/memory/lifecycle/stats"
_EP_VARIABLES = "/memory/variables"
_EP_TABLES = "/memory/tables"
_EP_EXTRACT_BATCH = "/memory/extraction/batch-extract"
_EP_GRAPH_QUERY = "/memory/graph/query"
_EP_GRAPH_EXTRACT = "/memory/graph/extract"


def _classify_error(exc: Exception) -> tuple[str, bool]:
    """异常分类 → (category, retryable)。

    category: timeout / connect / http_4xx / http_5xx / unknown；
    仅 timeout / connect / http_5xx 对幂等读操作可重试。
    """
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout", True
    # SDK 类型化异常：HTTPError 带 status_code，其余 TransportError 归为连接错误
    try:
        from agent_memory import exceptions as _sdk_exc
    except ImportError:  # SDK 为可选依赖，缺失时跳过 SDK 异常分类
        _sdk_exc = None
    if _sdk_exc is not None:
        if isinstance(exc, _sdk_exc.HTTPError):
            status_code = exc.status_code
            return ("http_5xx", True) if status_code >= 500 else ("http_4xx", False)
        if isinstance(exc, _sdk_exc.TransportError):
            return "connect", True
    try:
        import httpx
    except ImportError:  # httpx 随 SDK 可选安装，缺失时统一归为 unknown
        return "unknown", False
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", True
    if isinstance(exc, httpx.TransportError):
        return "connect", True
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return ("http_5xx", True) if status_code >= 500 else ("http_4xx", False)
    return "unknown", False


def _parse_error_response(resp: Any) -> tuple[str, str]:
    """解析 AMS 统一错误响应体（ErrorResponse：code/message/trace_id）。

    兼容 FastAPI 原生 {"detail": ...} 格式；解析失败回退原始文本截断。
    """
    try:
        data = resp.json()
    except Exception:
        return "", (getattr(resp, "text", "") or "")[:200]
    if isinstance(data, dict):
        code = str(data.get("code") or "")
        message = str(data.get("message") or data.get("detail") or "")[:200]
        return code, message
    return "", str(data)[:200]


def _log_http_status(operation: str, resp: Any) -> None:
    """对错误状态码分级记日志：4xx ERROR（解析 AMS 错误码），5xx WARNING。"""
    code, message = _parse_error_response(resp)
    if 400 <= resp.status_code < 500:
        hint = " — check memory.remote_api_key" if resp.status_code in (401, 403) else ""
        logger.error(
            "remote memory %s rejected: HTTP %d code=%s message=%s%s",
            operation, resp.status_code, code, message, hint,
        )
    else:
        logger.warning(
            "remote memory %s server error: HTTP %d code=%s message=%s",
            operation, resp.status_code, code, message,
        )


def _log_remote_error(operation: str, exc: Exception) -> str:
    """按分类分级记日志；对外行为不变（调用方仍返回空/None/False）。"""
    category, _ = _classify_error(exc)
    if category in ("timeout", "connect"):
        logger.warning(
            "remote memory %s failed: backend unreachable or timed out (%s: %s)",
            operation, category, exc,
        )
    elif category in ("http_4xx", "http_5xx"):
        resp = getattr(exc, "response", None)
        if resp is not None:
            _log_http_status(operation, resp)
        else:
            # SDK HTTPError：无原始响应对象，直接输出 status_code/detail
            status_code = int(getattr(exc, "status_code", 0) or 0)
            detail = str(getattr(exc, "detail", "") or "")[:200]
            if category == "http_4xx":
                hint = " — check memory.remote_api_key" if status_code in (401, 403) else ""
                logger.error(
                    "remote memory %s rejected: HTTP %d detail=%s%s",
                    operation, status_code, detail, hint,
                )
            else:
                logger.warning(
                    "remote memory %s server error: HTTP %d detail=%s",
                    operation, status_code, detail,
                )
    else:
        logger.warning("remote memory %s failed: %s", operation, exc)
    return category


def _check_degraded(operation: str, data: Any) -> None:
    """识别 AMS 响应中的降级信号（degraded / circuit_open）。

    区别于"后端不可达"：请求本身成功，但服务端处于降级/熔断状态。
    degrade_reason 字段固定拼在日志文本中，供观测系统采集识别降级类型。
    """
    if not isinstance(data, dict):
        return
    if data.get("circuit_open"):
        reason = "circuit_open"
    elif data.get("degraded"):
        reason = "degraded"
    else:
        return
    logger.warning(
        "remote memory %s degraded response: degrade_reason=%s "
        "(AMS server-side degradation, not a connectivity failure)",
        operation, reason,
    )


def _json_dict(operation: str, resp: Any) -> dict | None:
    """解析响应 JSON 并要求 dict 结构；否则记 WARNING 返回 None。

    统一防御非 JSON / 非 dict（如 list）响应体：避免 ``data.get`` 在
    try 块外抛 AttributeError，违反"记忆方法不抛异常"不变量。
    """
    try:
        data = resp.json()
    except Exception as exc:
        logger.warning("remote memory %s invalid response body: %s", operation, exc)
        return None
    if not isinstance(data, dict):
        logger.warning(
            "remote memory %s non-dict response body: %s", operation, str(data)[:200]
        )
        return None
    return data


def _ensure_dict(operation: str, data: Any) -> dict | None:
    """SDK 传输层已解析响应体防御：非 dict（如 list/str）记 WARNING 返回 None。"""
    if isinstance(data, dict):
        return data
    logger.warning(
        "remote memory %s non-dict response body: %s", operation, str(data)[:200]
    )
    return None


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
        # G5 混合搜索召回：默认关闭，独立超时预算；权重仅在配置时随请求传递
        self._hybrid_enabled = False
        self._hybrid_timeout = 15.0
        self._hybrid_weights: dict[str, float] = {}
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
            # Phase A：extraction 计数 + lifecycle 只读观测计数
            "extraction_total": 0,
            "extraction_failed": 0,
            "lifecycle_total": 0,
            "lifecycle_failed": 0,
            # Phase B1：三层召回计数
            "recall_layered_total": 0,
            "recall_layered_failed": 0,
            "recall_layered_fallback": 0,
            # Phase C1：图谱记忆计数
            "graph_query_total": 0,
            "graph_query_failed": 0,
            "graph_ingest_total": 0,
            "graph_ingest_failed": 0,
            # G5：混合搜索召回计数（fallback = 降级回单路语义召回次数）
            "hybrid_total": 0,
            "hybrid_failed": 0,
            "hybrid_fallback": 0,
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
        # G5 混合搜索（向量+BM25+实体+时间衰减融合）：多主题混合提问
        # 召回质量优化；失败自动降级单路语义召回，默认关闭。
        self._hybrid_enabled = bool(getattr(memory_cfg, "enable_hybrid_search", False))
        self._hybrid_timeout = float(getattr(memory_cfg, "hybrid_search_timeout", 15.0))
        # 权重 None = 不随请求传该字段，使用服务端默认融合权重
        self._hybrid_weights = {
            name: float(val)
            for name in ("alpha", "beta", "gamma", "delta")
            if (val := getattr(memory_cfg, f"hybrid_{name}", None)) is not None
        }
        if self._hybrid_enabled:
            # 运维确认召回路由模式：仅启动时输出一次，不在每次 recall 记日志
            logger.info(
                "hybrid search recall enabled: timeout=%.1fs weights=%s",
                self._hybrid_timeout,
                self._hybrid_weights or "server-default",
            )
        # AMS 只接受 amk_ 前缀的 API Key（其余会被当作 JWT 解析并 401）。
        # 格式错误只诊断不禁用：保持与现状一致的降级行为，请求失败仍静默。
        if not api_key.startswith("amk_"):
            logger.error(
                "memory.remote_api_key does not start with 'amk_' — "
                "agent-memory-system will reject it with 401; please issue an "
                "API key from the AMS console (Settings → API Keys)",
            )
        self._enabled = True
        logger.info("remote memory enabled: %s", base_url)

    def schedule_startup_check(self) -> None:
        """调度一次性异步连通性自检（main.py 启动流程调用）。

        不阻塞启动；未启用或无运行中事件循环时静默跳过。
        """
        if not self._enabled:
            return
        try:
            task = asyncio.get_running_loop().create_task(
                self._startup_connectivity_check(),
                name="remote-memory-startup-check",
            )
        except RuntimeError:
            logger.debug("remote memory startup check skipped: no running event loop")
            return
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _startup_connectivity_check(self) -> None:
        """启动时一次性轻量自检，区分三类诊断：后端不可达 / 401 无效 key / 正常。

        - GET {base}/health/live：免鉴权，探连通性（AMS health 路由）
        - GET {base}/system/llm/resilience：需鉴权且为内存快照（轻量），探 key 有效性
        任何失败只记日志，绝不抛异常、不阻塞启动主流程。
        """
        base = self._base_url.rstrip("/")
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as http:
                try:
                    resp = await http.get(f"{base}{_EP_HEALTH_LIVE}", timeout=3.0)
                except Exception as exc:
                    logger.error(
                        "remote memory startup check: backend unreachable at %s (%s) — "
                        "recall/save will silently degrade until it recovers",
                        base, exc,
                    )
                    return
                if resp.status_code >= 400:
                    logger.warning(
                        "remote memory startup check: %s/health/live returned HTTP %d",
                        base, resp.status_code,
                    )
                auth_resp = await http.get(
                    f"{base}{_EP_RESILIENCE}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                if auth_resp.status_code in (401, 403):
                    code, message = _parse_error_response(auth_resp)
                    logger.error(
                        "remote memory startup check: API key rejected (HTTP %d "
                        "code=%s message=%s) — check memory.remote_api_key",
                        auth_resp.status_code, code, message,
                    )
                elif auth_resp.status_code >= 400:
                    logger.warning(
                        "remote memory startup check: auth probe returned HTTP %d",
                        auth_resp.status_code,
                    )
                else:
                    logger.info("remote memory startup check OK: %s", base)
        except Exception as exc:  # 自检本身绝不影响启动
            logger.warning("remote memory startup check failed: %s", exc)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # ================================================================
    # FR-6 可观测性
    # ================================================================

    def _bump(self, counter: str) -> None:
        """累加计数器；每 _STATS_LOG_EVERY 次读写操作输出一行汇总日志。"""
        self._stats[counter] += 1
        ops = (
            self._stats["recall_total"]
            + self._stats["save_total"]
            + self._stats["hybrid_total"]
        )
        if ops and ops % _STATS_LOG_EVERY == 0:
            logger.info(
                "remote memory stats: recall %d/%d hit, save %d total / %d failed, "
                "table write %d total / %d failed, layered recall %d total / %d failed / %d fallback, "
                "hybrid recall %d total / %d failed / %d fallback, "
                "graph query %d total / %d failed, graph ingest %d total / %d failed, "
                "extraction %d total / %d failed, lifecycle %d total / %d failed",
                self._stats["recall_hit"], self._stats["recall_total"],
                self._stats["save_total"], self._stats["save_failed"],
                self._stats["table_write_total"], self._stats["table_write_failed"],
                self._stats["recall_layered_total"], self._stats["recall_layered_failed"],
                self._stats["recall_layered_fallback"],
                self._stats["hybrid_total"], self._stats["hybrid_failed"],
                self._stats["hybrid_fallback"],
                self._stats["graph_query_total"], self._stats["graph_query_failed"],
                self._stats["graph_ingest_total"], self._stats["graph_ingest_failed"],
                self._stats["extraction_total"], self._stats["extraction_failed"],
                self._stats["lifecycle_total"], self._stats["lifecycle_failed"],
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
            # 客户端级超时取长路径上限（extraction 30s）；各调用点均以
            # asyncio.wait_for / _retry_read 收紧到自身预算
            self._client = AsyncMemoryClient(
                base_url=self._base_url,
                api_key=self._api_key,
                timeout=max(self._timeout, 30.0),
            )
        return self._client

    async def _retry_read(
        self, operation: str, attempt: Any, *, timeout: float | None = None
    ) -> Any:
        """幂等读操作统一重试入口（recall/query/list 等）。

        attempt 为无参协程工厂（每次调用产生新协程）。timeout/连接错误/5xx
        按 _RETRY_BACKOFFS 指数退避重试，总耗时不突破 timeout 预算；
        4xx 不重试。最终失败抛最后一个异常，由调用方分级记日志并降级。
        """
        budget = self._timeout if timeout is None else timeout
        deadline = time.monotonic() + budget
        last_exc: Exception | None = None
        for i in range(len(_RETRY_BACKOFFS) + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                return await asyncio.wait_for(attempt(), timeout=remaining)
            except Exception as exc:
                last_exc = exc
                category, retryable = _classify_error(exc)
                backoff = _RETRY_BACKOFFS[i] if i < len(_RETRY_BACKOFFS) else None
                if (
                    not retryable
                    or backoff is None
                    or time.monotonic() + backoff >= deadline
                ):
                    raise
                logger.warning(
                    "remote memory %s attempt %d failed (%s), retrying in %.1fs",
                    operation, i + 1, category, backoff,
                )
                await asyncio.sleep(backoff)
        if last_exc is not None:
            raise last_exc
        raise asyncio.TimeoutError(f"{operation} retry budget exhausted")

    async def _sdk_request(self, method: str, path: str, **kwargs: Any) -> Any:
        """经 SDK 公开 request() 透传；旧版 SDK 回退私有传输层。

        AsyncMemoryClient 的高层便捷方法内部吞异常且（部分）丢弃原始
        响应体，会令 _retry_read 重试、分级错误处理、失败计数与
        _check_degraded 降级识别全部失效；故此类端点改走 SDK 公开
        request()（>=0.1.1 提供）：不吞异常、不改写响应体，复用其鉴权头、
        /api/v1 前缀补齐、连接池与类型化异常
        （agent_memory.exceptions.HTTPError/TransportError）。

        旧版 SDK（无公开 request()）回退 client._transport.request()，
        并记一条 WARNING（每进程首次）提示升级。
        """
        global _SDK_TRANSPORT_FALLBACK_WARNED
        client = self._get_client()
        if client is None:
            raise RuntimeError("remote memory SDK client unavailable")
        req = getattr(client, "request", None)
        if callable(req):
            return await req(method, path, **kwargs)
        if not _SDK_TRANSPORT_FALLBACK_WARNED:
            _SDK_TRANSPORT_FALLBACK_WARNED = True
            logger.warning(
                "agent-memory-sdk 无公开 request()，回退私有传输层 _transport；"
                "建议升级 agent-memory-sdk>=0.1.1"
            )
        return await client._transport.request(method, path, **kwargs)

    # ================================================================
    # 召回（读路径）
    # ================================================================

    async def recall(self, query: str, routing_key: str = "", top_k: int | None = None) -> str:
        """用 query 召回长期记忆上下文。失败/超时/空结果一律返回空串。

        memory.enable_hybrid_search 开启时路由到混合搜索召回（内部
        失败自动降级回单路语义召回），调用方零改动。
        """
        if self._get_client() is None or not query.strip():
            return ""
        if self._hybrid_enabled:
            return await self.recall_hybrid(query, top_k=top_k)
        return await self._recall_semantic(query, top_k)

    async def _recall_semantic(self, query: str, top_k: int | None = None) -> str:
        """单路语义召回（原 recall 主体），也是混合搜索的降级路径。"""
        client = self._get_client()
        if client is None:
            return ""
        self._bump("recall_total")
        try:
            context = await self._retry_read(
                "recall",
                lambda: client.recall_context(query, top_k=top_k or self._recall_top_k),
            )
        except Exception as exc:
            _log_remote_error("recall", exc)
            return ""
        if not context:
            return ""
        self._bump("recall_hit")
        return self._clip_context(context)

    def _clip_context(self, context: str) -> str:
        """按 recall_max_chars 截断召回上下文，防止挤占上下文窗口。"""
        if len(context) > self._recall_max_chars:
            marker = "...(截断)"
            return context[: self._recall_max_chars - len(marker)] + marker
        return context

    async def recall_hybrid(self, query: str, top_k: int | None = None) -> str:
        """G5 混合搜索召回（POST /memory/hybrid-search，向量+BM25+实体+时间融合）。

        针对多主题混合提问下单路语义召回排序被稀释的场景。独立超时
        预算 hybrid_search_timeout（服务端 P99 约 800ms，高于普通召回）。
        任何失败/超时/非 dict/空结果都降级调用 _recall_semantic（而非
        recall() 本身，避免开关开启时的递归），绝不抛异常。
        """
        if self._get_client() is None or not query.strip():
            return ""
        self._bump("hybrid_total")
        effective_top_k = top_k or self._recall_top_k
        payload: dict[str, Any] = {
            "query": query.strip(),
            "top_k": effective_top_k,
            # 分页字段与 HybridSearchRequest 契约对齐：召回只取首页 top_k 条
            "offset": 0,
            "limit": effective_top_k,
            # 权重仅在配置时随请求传递，否则用服务端默认融合权重
            **self._hybrid_weights,
        }
        try:
            raw = await self._retry_read(
                "recall_hybrid",
                lambda: self._sdk_request("POST", _EP_HYBRID_SEARCH, json=payload),
                timeout=self._hybrid_timeout,
            )
            data = _ensure_dict("recall_hybrid", raw)
            if data is None:
                self._bump("hybrid_failed")
            else:
                _check_degraded("recall_hybrid", data)
                fragments = data.get("fragments", data.get("results", []))
                if isinstance(fragments, list):
                    parts = [
                        str(f.get("content", "")).strip()
                        for f in fragments
                        if isinstance(f, dict) and str(f.get("content", "")).strip()
                    ]
                    if parts:
                        return self._clip_context("\n".join(parts))
                # 空结果不计入 failed（可能 FTS 索引未建/无相关记忆），仍回退
        except Exception as exc:
            _log_remote_error("recall_hybrid", exc)
            self._bump("hybrid_failed")
        self._bump("hybrid_fallback")
        logger.debug("recall_hybrid falling back to semantic recall")
        return await self._recall_semantic(query, top_k)

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

            _recall_timeout = max(self._timeout, 15.0)

            async def _attempt() -> Any:
                async with httpx.AsyncClient() as _client:
                    resp = await _client.post(
                        f"{self._base_url.rstrip('/')}{_EP_RECALL_AUTO}",
                        json={
                            "query": query,
                            "token_budget": token_budget,
                            "layers": ["profile", "semantic", "entity_expansion"],
                        },
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        timeout=_recall_timeout,
                    )
                resp.raise_for_status()
                return resp

            resp = await self._retry_read(
                "recall_layered", _attempt, timeout=_recall_timeout
            )

            data = _json_dict("recall_layered", resp)
            if data is None:
                self._bump("recall_layered_failed")
                return await self._fallback_layered_recall(query)
            _check_degraded("recall_layered", data)
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

        except Exception as exc:
            _log_remote_error("recall_layered", exc)
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
    ) -> bool:
        """把一轮对话写为记忆片段。任何失败只记日志，不向上抛。

        fragment_type: 记忆类型（info / preference / plan）。
        importance: 显式 importance 分；None 时使用启发式打分。

        Returns:
            True 写入成功；False 表示禁用/超时/失败（供 memory_sync
            双写路径判断远程结果，其余 fire-and-forget 调用方可忽略）。
        """
        client = self._get_client()
        if client is None:
            return False
        # FR-4 摘要优先级：调用方提供 > LLM 一句话摘要 > 原文拼接回退
        content = summary.strip() or await self._summarize_turn(user_message, assistant_reply) or (
            f"用户：{user_message[:500]}\n助手：{assistant_reply[:1000]}"
        )
        # FR-3 生命周期：差异化 TTL（按 fragment_type）+ 启发式 importance
        ttl_days = _FRAGMENT_TTL_DAYS.get(fragment_type, self._fragment_ttl_days)
        ttl_seconds = ttl_days * 86400 if ttl_days else None
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
            return True
        except asyncio.TimeoutError:
            self._bump("save_failed")
            logger.warning("remote memory save_turn timed out (%.1fs)", self._timeout)
            return False
        except Exception as exc:
            # 写路径 fire-and-forget：不重试，只分级记日志
            self._bump("save_failed")
            _log_remote_error("save_turn", exc)
            return False

    async def list_fragments(
        self,
        *,
        status: str = "active",
        session_ids: list[str] | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """拉取远程记忆片段列表（memory_sync 全量同步用）。失败返回空列表。"""
        if not self._enabled:
            return []
        params: dict[str, str] = {"status": status, "limit": str(limit)}
        if session_ids:
            params["session_ids"] = ",".join(session_ids)
        try:
            import httpx

            _list_timeout = max(self._timeout, 60.0)

            async def _attempt() -> Any:
                async with httpx.AsyncClient(timeout=_list_timeout) as http:
                    resp = await http.get(
                        f"{self._base_url.rstrip('/')}{_EP_FRAGMENTS}",
                        params=params,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                    )
                resp.raise_for_status()
                return resp

            resp = await self._retry_read(
                "list_fragments", _attempt, timeout=_list_timeout
            )
            data = _json_dict("list_fragments", resp)
            if data is None:
                return []
            fragments = data.get("fragments", [])
            return fragments if isinstance(fragments, list) else []
        except Exception as exc:
            _log_remote_error("list_fragments", exc)
            return []

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
            _log_remote_error(f"set_preference({key})", exc)
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
            variables = await self._retry_read(
                "get_preferences", lambda: client.list_variables()
            )
        except Exception as exc:
            _log_remote_error("get_preferences", exc)
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
                f"{self._base_url.rstrip('/')}{_EP_VARIABLES}",
                json={"key": key.strip(), "value": value, "ttl": None},
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
            if resp.status_code >= 400:
                _log_http_status(f"set_preference_sync({key})", resp)
                return False
            return True
        except Exception as exc:
            _log_remote_error(f"set_preference_sync({key})", exc)
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
            _log_remote_error(f"table request {method} {path}", exc)
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
            "POST", _EP_TABLES,
            json={"table_name": table_name, "fields": fields},
        )
        if resp is None:
            return False
        if resp.status_code < 400 or "exist" in resp.text.lower():
            self._ensured_tables.add(table_name)
            return True
        _log_http_status(f"ensure_table({table_name})", resp)
        return False

    def add_record_sync(self, table_name: str, record: dict) -> int | None:
        """插入一条记录，返回新记录 ID；失败返回 None。"""
        if not self.ensure_table_sync(table_name):
            return None
        self._bump("table_write_total")
        resp = self._table_request_sync(
            "POST", f"{_EP_TABLES}/{table_name}/records", json={"record": record},
        )
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                _log_http_status(f"add_record({table_name})", resp)
            self._bump("table_write_failed")
            return None
        data = _json_dict(f"add_record({table_name})", resp)
        if data is None:
            return None
        record_id = data.get("record_id", data.get("id"))
        if record_id is None:
            # 响应字段防御：record_id/id 均缺失时明确失败，避免 NoneType 下游错误
            logger.warning(
                "remote memory add_record(%s) response missing record_id/id: %s",
                table_name, str(data)[:200],
            )
            return None
        return record_id

    def update_record_sync(self, table_name: str, record_id: int, updates: dict) -> bool:
        """按 record_id 更新既有记录。失败返回 False。"""
        if not self.ensure_table_sync(table_name):
            return False
        self._bump("table_write_total")
        resp = self._table_request_sync(
            "PUT", f"{_EP_TABLES}/{table_name}/records",
            json={"updates": updates}, params={"record_id": record_id},
        )
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                _log_http_status(f"update_record({table_name})", resp)
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
            "POST", f"{_EP_TABLES}/{table_name}/query",
            json={"filters": filters or None, "limit": limit},
        )
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                _log_http_status(f"query_records({table_name})", resp)
            return None
        data = _json_dict(f"query_records({table_name})", resp)
        if data is None:
            return None
        records = data.get("records")
        if not isinstance(records, list):
            # 响应字段防御：records 缺失/类型不对时明确失败
            logger.warning(
                "remote memory query_records(%s) response missing 'records' list",
                table_name,
            )
            return None
        return records

    # ================================================================
    # Phase A1: Extraction API（LLM 驱动的结构化记忆抽取）
    # ================================================================

    async def extract_and_save(self, session_id: str, messages: list[dict]) -> dict:
        """调用 agent-memory-system 的 extraction API，从对话中抽取结构化记忆。

        流程：
        1. 调用 POST {base_url}/memory/extraction/batch-extract
        2. 解析返回 {variables, facts, preferences, plans}
        3. 分类写入各类型记忆
        4. 返回统计 {extracted: N, saved: N, errors: [...]}

        超时 30s，失败不抛异常，log warning 后返回空统计。
        """
        if not self._enabled or self._get_client() is None:
            return {"extracted": 0, "saved": 0, "errors": []}
        self._bump("extraction_total")
        empty: dict = {"extracted": 0, "saved": 0, "errors": []}
        try:
            raw = await asyncio.wait_for(
                self._sdk_request(
                    "POST", _EP_EXTRACT_BATCH,
                    json={"session_id": session_id, "conversation_history": messages},
                ),
                timeout=30.0,
            )
            data = _ensure_dict("extraction", raw)
            if data is None:
                self._bump("extraction_failed")
                return empty
            _check_degraded("extraction", data)
        except Exception as exc:
            # 写路径（触发服务端 LLM 抽取）：不重试，分级记日志后降级
            _log_remote_error("extraction", exc)
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
        """内部辅助：写入单条语义记忆片段（差异化 TTL）。"""
        client = self._get_client()
        if client is None:
            return
        ttl_days = _FRAGMENT_TTL_DAYS.get(fragment_type, self._fragment_ttl_days)
        ttl_seconds = ttl_days * 86400 if ttl_days else None
        await asyncio.wait_for(
            client.remember_fragment(
                content=content[: self._max_save_length],
                fragment_type=fragment_type,
                importance_score=self._importance_default,
                ttl=ttl_seconds,
            ),
            timeout=self._timeout,
        )

    # ================================================================
    # Phase A2: Lifecycle 只读观测
    #
    # 治理动作（run-cleanup / duplicates）已上收 AMS 服务端调度器，
    # 玄机侧不再主动触发，只保留只读状态查询供观测/诊断使用。
    # ================================================================

    async def get_lifecycle_stats(self) -> dict:
        """只读拉取记忆生命周期统计（GET /memory/lifecycle/stats）。

        不触发任何治理动作；失败降级返回空 dict。
        """
        if not self._enabled:
            return {}
        self._bump("lifecycle_total")
        try:
            import httpx

            async def _attempt() -> Any:
                async with httpx.AsyncClient(timeout=self._timeout) as http:
                    resp = await http.get(
                        f"{self._base_url.rstrip('/')}{_EP_LIFECYCLE_STATS}",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                    )
                resp.raise_for_status()
                return resp

            resp = await self._retry_read("lifecycle_stats", _attempt)
            data = resp.json()
            _check_degraded("lifecycle_stats", data)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            _log_remote_error("lifecycle_stats", exc)
            self._bump("lifecycle_failed")
            return {}

    async def get_resilience_status(self) -> dict:
        """只读拉取 AMS 服务端容错状态（GET /system/llm/resilience）。

        返回断路器快照与重试队列统计，供降级诊断；失败返回空 dict。
        """
        if not self._enabled:
            return {}
        try:
            import httpx

            async def _attempt() -> Any:
                async with httpx.AsyncClient(timeout=self._timeout) as http:
                    resp = await http.get(
                        f"{self._base_url.rstrip('/')}{_EP_RESILIENCE}",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                    )
                resp.raise_for_status()
                return resp

            resp = await self._retry_read("resilience_status", _attempt)
            data = resp.json()
            # 断路器处于 open 状态 → 记降级信号（区别于后端不可达）
            if isinstance(data, dict):
                breakers = data.get("circuit_breakers") or {}
                open_breakers = [
                    name for name, snap in breakers.items()
                    if isinstance(snap, dict) and snap.get("state") == "open"
                ]
                if open_breakers:
                    logger.warning(
                        "remote memory resilience_status degraded response: "
                        "degrade_reason=circuit_open breakers=%s",
                        open_breakers,
                    )
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            _log_remote_error("resilience_status", exc)
            return {}

    # ================================================================
    # Phase C1: Graph Memory（实体-关系图谱查询与摄取）
    # ================================================================

    async def graph_query(self, entity: str, *, depth: int = 2) -> list[dict]:
        """查询实体关联图谱。

        1. 调用 GET {base_url}/memory/graph/query?q={entity}
        2. 返回 [{"entity": str, "relation": str, "target": str, "weight": float}, ...]
        3. 超时 10s，失败返回空列表
        4. 添加 _stats 计数：graph_query_total / graph_query_failed
        """
        if not self._enabled or not entity.strip() or self._get_client() is None:
            return []
        self._bump("graph_query_total")
        try:
            _graph_timeout = 10.0

            async def _attempt() -> Any:
                return await self._sdk_request(
                    "GET", _EP_GRAPH_QUERY, params={"q": entity.strip()},
                )

            raw = await self._retry_read("graph_query", _attempt, timeout=_graph_timeout)
            data = _ensure_dict("graph_query", raw)
            if data is None:
                self._bump("graph_query_failed")
                return []
            _check_degraded("graph_query", data)
            # 标准化返回格式；对 neighbors 结构显式防御，诊断信息清晰
            neighbors = data.get("neighbors", data.get("results", []))
            if not isinstance(neighbors, list):
                logger.warning(
                    "remote memory graph_query response 'neighbors' is not a list: %s",
                    str(neighbors)[:200],
                )
                self._bump("graph_query_failed")
                return []
            results: list[dict] = []
            for n in neighbors:
                if not isinstance(n, dict):
                    logger.warning(
                        "remote memory graph_query skipping non-dict neighbor: %s",
                        str(n)[:100],
                    )
                    continue
                results.append({
                    "entity": n.get("entity_name", n.get("entity", "")),
                    "relation": n.get("relation_type", n.get("relation", "")),
                    "target": n.get("entity_name", n.get("target", "")),
                    "weight": float(n.get("confidence", n.get("weight", 0.5))),
                })
            return results
        except Exception as exc:
            _log_remote_error("graph_query", exc)
            self._bump("graph_query_failed")
            return []

    async def graph_ingest(self, text: str, *, session_id: str | None = None) -> dict:
        """从文本中抽取实体和关系，写入图谱。

        1. 调用 POST {base_url}/memory/graph/extract
           body: {"text": text}
        2. 返回 {"entities_extracted": N, "relations_created": N}
        3. 超时 15s，失败返回空统计
        4. 添加 _stats 计数：graph_ingest_total / graph_ingest_failed

        注意：这是 fire-and-forget 操作，调用方不需要等待结果。
        """
        empty = {"entities_extracted": 0, "relations_created": 0}
        if not self._enabled or not text.strip() or self._get_client() is None:
            return empty
        self._bump("graph_ingest_total")
        try:
            _ingest_timeout = max(self._timeout, 15.0)
            raw = await asyncio.wait_for(
                self._sdk_request("POST", _EP_GRAPH_EXTRACT, json={"text": text}),
                timeout=_ingest_timeout,
            )
            data = _ensure_dict("graph_ingest", raw)
            if data is None:
                self._bump("graph_ingest_failed")
                return empty
            _check_degraded("graph_ingest", data)
            result = {
                "entities_extracted": data.get("entities_extracted", data.get("stored", {}).get("entities", 0)),
                "relations_created": data.get("relations_created", data.get("stored", {}).get("relationships", 0)),
            }
            logger.info(
                "graph_ingest success: entities=%d relations=%d",
                result["entities_extracted"], result["relations_created"],
            )
            return result
        except Exception as exc:
            # 写路径 fire-and-forget：不重试，分级记日志后降级
            _log_remote_error("graph_ingest", exc)
            self._bump("graph_ingest_failed")
            return empty

    # ================================================================
    # P3: 用户偏好变量化迁移（memory.md → Variables）
    # ================================================================

    async def migrate_preferences_to_variables(self, file_path: str) -> dict:
        """读取 memory.md 中的偏好条目，对比现有 Variables，将缺失的补写入。

        流程：
        1. 读取远程 Variables 现有键集合
        2. 解析 memory.md 中 ``## 用户重要事项`` 章节下的条目
        3. 对每个条目生成 key，若 key 不在现有 Variables 中则写入

        返回 {"migrated": N, "skipped_existing": N, "errors": [...]}。
        """
        result = {"migrated": 0, "skipped_existing": 0, "errors": []}
        if not self._enabled:
            return result

        # 1. 读取现有 Variables 键集合
        try:
            existing_vars = await self.get_preferences()
        except Exception as exc:
            logger.warning("migrate_preferences: get_preferences failed: %s", exc)
            existing_vars = {}
        existing_keys = set(existing_vars.keys())

        # 2. 读取并解析 memory.md
        try:
            from pathlib import Path as _Path
            md = _Path(file_path)
            if not md.exists():
                logger.info("migrate_preferences: file not found: %s", file_path)
                return result
            text = md.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("migrate_preferences: read file failed: %s", exc)
            result["errors"].append(str(exc))
            return result

        # 提取 "## 用户重要事项" 章节内容
        section_lines: list[str] = []
        in_section = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## ") and "用户重要事项" in stripped:
                in_section = True
                continue
            if in_section:
                if stripped.startswith("## "):
                    break  # 下一个章节
                if not stripped or stripped.startswith(">"):
                    continue
                section_lines.append(stripped)

        if not section_lines:
            logger.info("migrate_preferences: no preference entries found in %s", file_path)
            return result

        # 3. 逐行解析，对比现有 Variables，缺失的补写入
        kv_pattern = re.compile(r"^[-*•]?\s*(.+?)[:=]\s*(.+)$")
        for line in section_lines:
            clean = re.sub(r"^[-*•]\s+", "", line).strip()
            if not clean:
                result["skipped_existing"] += 1
                continue
            m = kv_pattern.match(clean)
            if m:
                key, value = m.group(1).strip(), m.group(2).strip()
            else:
                key = clean[:20].rstrip("，。,. ")
                value = clean

            # 跳过已存在的 key
            if key in existing_keys:
                result["skipped_existing"] += 1
                continue

            try:
                ok = await self.set_preference(key, value)
                if ok:
                    result["migrated"] += 1
                    existing_keys.add(key)  # 防止同文件重复 key
                else:
                    result["errors"].append(f"set_preference({key}) returned False")
            except Exception as exc:
                result["errors"].append(f"set_preference({key}): {exc}")

        logger.info(
            "migrate_preferences complete: migrated=%d skipped_existing=%d errors=%d",
            result["migrated"], result["skipped_existing"], len(result["errors"]),
        )
        return result

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

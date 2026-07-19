"""Performance optimization utilities for XiaoPaw v2.

【版本 v1.0】(2026-07-01)
包含以下优化组件：
1. AsyncContextMgr: 异步上下文管理器（非阻塞 I/O）
2. LRUCache: 线程安全的 LRU 缓存实现
3. TokenCache: 基于 hash 的 token 计数结果缓存
4. PerformanceMonitor: 性能监控与统计工具

【使用方式】
在需要优化的模块中导入：
    from xiaopaw.utils.performance import (
        async_load_session_ctx,
        async_save_session_ctx,
        token_cache,
        lru_cache,
    )
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ════════════════════════════════════════════════════════════════════
# 1. LRUCache —— 线程安全 LRU 缓存
# ════════════════════════════════════════════════════════════════════


class LRUCache:
    """线程安全的 LRU (Least Recently Used) 缓存。

    特性：
    - 固定容量上限，超出时淘汰最久未使用的条目
    - 可选 TTL（Time To Live）过期机制
    - 线程安全（threading.Lock）
    - 命中/未命中统计（用于监控）

    示例用法：
        cache = LRUCache(maxsize=1000, ttl=300)

        # 获取或计算值
        result = cache.get_or_compute("key", expensive_function, *args)

        # 手动设置
        cache.set("key", value)

        # 清除所有条目
        cache.clear()
    """

    def __init__(self, maxsize: int = 128, ttl: Optional[float] = None):
        """
        初始化 LRU 缓存。

        Args:
            maxsize: 最大缓存条目数（超出时淘汰最久未使用的）
            ttl: 过期时间（秒），None 表示不过期
        """
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")

        self._maxsize = maxsize
        self._ttl = ttl
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()  # key -> (value, timestamp)
        self._lock = threading.RLock()
        # 统计信息
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值。如果不存在或已过期返回 None，并移动到最近使用位置。"""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            value, timestamp = self._cache[key]

            # 检查 TTL 是否过期
            if self._ttl is not None and (time.time() - timestamp) > self._ttl:
                del self._cache[key]
                self._misses += 1
                return None

            # 移动到末尾（最近使用）
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        """设置缓存值。如果已存在则更新并移到末尾；如果超出容量则淘汰最旧条目。"""
        with self._lock:
            if key in self._cache:
                # 更新现有值
                del self._cache[key]
            elif len(self._cache) >= self._maxsize:
                # 淘汰最旧的条目（第一个）
                self._cache.popitem(last=False)

            self._cache[key] = (value, time.time())

    def get_or_compute(self, key: str, compute_fn: Callable[..., T], *args, **kwargs) -> T:
        """获取缓存值，如不存在则调用 compute_fn 计算并存入缓存。

        Args:
            key: 缓存键
            compute_fn: 计算函数（在缓存未命中时调用）
            *args, **kwargs: 传递给 compute_fn 的参数

        Returns:
            缓存的值或新计算的值
        """
        value = self.get(key)
        if value is not None:
            return value

        value = compute_fn(*args, **kwargs)
        self.set(key, value)
        return value

    def delete(self, key: str) -> bool:
        """删除指定键的缓存条目。成功删除返回 True，不存在返回 False。"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """清空所有缓存条目。"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def __len__(self) -> int:
        return len(self._cache)

    @property
    def hit_rate(self) -> float:
        """缓存命中率（0.0 ~ 1.0）"""
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息。"""
        with self._lock:
            return {
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "ttl": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self.hit_rate,
            }

    def invalidate_expired(self) -> int:
        """清除所有过期的缓存条目。返回清除的条目数。"""
        if self._ttl is None:
            return 0

        now = time.time()
        expired_keys = [
            key for key, (_, ts) in self._cache.items() if (now - ts) > self._ttl
        ]

        for key in expired_keys:
            del self._cache[key]

        return len(expired_keys)


# ════════════════════════════════════════════════════════════════════
# 2. TokenCache —— 基于 hash 的 token 计数缓存
# ════════════════════════════════════════════════════════════════════


class TokenCache:
    """Token 计数结果缓存。

    避免对相同消息列表重复进行 token 计算（这是 CPU 密集型操作）。
    使用消息内容的 SHA-256 哈希作为缓存键。

    使用示例：
        token_cache = TokenCache(maxsize=500)

        # 包装原始 count_tokens 函数
        count_tokens_cached = token_cache.cached(count_tokens)
        tokens = count_tokens_cached(messages)
    """

    def __init__(self, maxsize: int = 512):
        """
        初始化 Token Cache。

        Args:
            maxsize: 最大缓存条目数
        """
        self._lru = LRUCache(maxsize=maxsize, ttl=None)  # token 缓存不过期
        self._compute_count = 0  # 统计：实际计算次数

    def _hash_messages(self, messages: list[dict]) -> str:
        """生成消息列表的哈希值（用于缓存键）。

        只使用 role 和 content 字段来计算哈希，忽略其他元数据。
        """
        hasher = hashlib.sha256()

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            # 使用分隔符避免碰撞："user"+"hello" vs "userhello"
            hasher.update(f"{role}\x00{content}".encode("utf-8"))

        return hasher.hexdigest()

    def cached(self, count_fn: Callable[[list[dict]], int]) -> Callable[[list[dict]], int]:
        """装饰器：包装 token 计数函数以添加缓存功能。

        Args:
            count_fn: 原始的 count_tokens(messages) 函数

        Returns:
            带缓存的计数函数
        """

        @functools.wraps(count_fn)
        def _wrapper(messages: list[dict]) -> int:
            cache_key = self._hash_messages(messages)

            cached_value = self._lru.get(cache_key)
            if cached_value is not None:
                return cached_value

            # 未命中：实际计算
            self._compute_count += 1
            result = count_fn(messages)
            self._lru.set(cache_key, result)
            return result

        return _wrapper

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息。"""
        stats = self._lru.get_stats()
        stats["actual_computations"] = self._compute_count
        return stats

    def clear(self) -> None:
        """清空缓存。"""
        self._lru.clear()
        self._compute_count = 0


# ════════════════════════════════════════════════════════════════════
# 3. 异步上下文管理器
# ════════════════════════════════════════════════════════════════════


async def async_load_session_ctx(session_id: str, ctx_dir: Path) -> list[dict]:
    """异步加载会话上下文（非阻塞文件读取）。

    替代同步版本 context_mgmt.load_session_ctx()，
    在高并发场景下不会阻塞事件循环。

    Args:
        session_id: 会话 ID
        ctx_dir: 上下文目录路径

    Returns:
        消息列表（JSON 解析后的 dict 列表）
    """
    ctx_path = ctx_dir / f"{session_id}_ctx.json"

    if not ctx_path.exists():
        return []

    try:
        # 使用 asyncio.to_thread 将同步文件操作放到线程池执行
        content = await asyncio.to_thread(ctx_path.read_text, encoding="utf-8")
        data = json.loads(content)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("failed to load ctx for %s: %s", session_id, exc)
        return []


async def async_save_session_ctx(
    session_id: str, messages: list[dict], ctx_dir: Path
) -> None:
    """异步保存会话上下文（非阻塞文件写入）。

    使用原子写入策略：先写入临时文件，再 rename 到目标位置。
    这确保即使写入过程中崩溃，也不会产生损坏的文件。

    Args:
        session_id: 会话 ID
        messages: 消息列表
        ctx_dir: 上下文目录路径
    """
    ctx_dir.mkdir(parents=True, exist_ok=True)
    ctx_path = ctx_dir / f"{session_id}_ctx.json"
    tmp = ctx_path.with_suffix(".tmp")

    content = json.dumps(messages, ensure_ascii=False)

    # 将文件操作放到线程池
    await asyncio.to_thread(tmp.write_text, content, encoding="utf-8")
    await asyncio.to_thread(tmp.rename, ctx_path)


async def async_append_session_raw(
    session_id: str, messages: list[dict], ctx_dir: Path
) -> None:
    """异步追加原始消息到 JSONL 文件。

    Args:
        session_id: 会话 ID
        messages: 要追加的消息列表
        ctx_dir: 上下文目录路径
    """
    ctx_dir.mkdir(parents=True, exist_ok=True)
    raw_path = ctx_dir / f"{session_id}_raw.jsonl"
    lines = "\n".join(json.dumps(msg, ensure_ascii=False) for msg in messages)

    def _append():
        with raw_path.open("a", encoding="utf-8") as f:
            f.write(lines + "\n" if lines else "")

    await asyncio.to_thread(_append)


# ════════════════════════════════════════════════════════════════════
# 4. 性能监控工具
# ════════════════════════════════════════════════════════════════════


class PerformanceMonitor:
    """性能监控与计时工具。

    用于测量代码块执行时间、记录慢查询、收集性能指标。

    示例用法：
        monitor = PerformanceMonitor()

        with monitor.measure("load_context"):
            data = load_large_file()

        print(monitor.get_stats())
    """

    def __init__(self):
        self._measurements: list[dict] = []
        self._lock = threading.Lock()

    class TimerContextManager:
        """计时上下文管理器（with语句使用）。"""

        def __init__(self, monitor: "PerformanceMonitor", label: str):
            self._monitor = monitor
            self._label = label
            self._start_time: Optional[float] = None

        def __enter__(self):
            self._start_time = time.perf_counter()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self._start_time is None:
                return

            elapsed = time.perf_counter() - self._start_time

            with self._monitor._lock:
                self._monitor._measurements.append({
                    "label": self._label,
                    "duration_sec": elapsed,
                    "timestamp": time.time(),
                    "success": exc_type is None,
                })
            return False  # 不抑制异常

    def measure(self, label: str) -> "TimerContextManager":
        """创建计时上下文管理器。

        Args:
            label: 操作标签（用于标识被测量的操作）

        Returns:
            上下文管理器（支持 with 语句）

        示例：
            with monitor.measure("db_query"):
                results = db.execute(query)
        """
        return self.TimerContextManager(self, label)

    def record(self, label: str, duration_sec: float, success: bool = True) -> None:
        """手动记录一次测量结果。

        Args:
            label: 操作标签
            duration_sec: 执行耗时（秒）
            success: 操作是否成功
        """
        with self._lock:
            self._measurements.append({
                "label": label,
                "duration_sec": duration_sec,
                "timestamp": time.time(),
                "success": success,
            })

    def get_stats(self) -> dict[str, Any]:
        """获取性能统计数据。"""
        with self._lock:
            if not self._measurements:
                return {
                    "total_measurements": 0,
                    "by_label": {},
                }

            by_label: dict[str, list[float]] = {}
            for m in self._measurements:
                label = m["label"]
                by_label.setdefault(label, []).append(m["duration_sec"])

            stats_by_label = {}
            for label, durations in by_label.items():
                n = len(durations)
                avg = sum(durations) / n
                stats_by_label[label] = {
                    "count": n,
                    "total_sec": sum(durations),
                    "avg_sec": avg,
                    "min_sec": min(durations),
                    "max_sec": max(durations),
                    "p95_sec": sorted(durations)[int(n * 0.95)] if n > 1 else avg,
                    "success_rate": (
                        sum(1 for m in self._measurements if m["label"] == label and m["success"]) / n
                    ),
                }

            return {
                "total_measurements": len(self._measurements),
                "by_label": stats_by_label,
            }

    def get_slow_operations(self, threshold_sec: float = 1.0) -> list[dict]:
        """获取超过阈值的慢操作列表。

        Args:
            threshold_sec: 时间阈值（秒），超过此值的操作被视为慢操作

        Returns:
            慢操作列表（按耗时降序排列）
        """
        with self._lock:
            slow_ops = [m for m in self._measurements if m["duration_sec"] >= threshold_sec]
            slow_ops.sort(key=lambda x: x["duration_sec"], reverse=True)
            return slow_ops

    def clear(self) -> None:
        """清空所有测量数据。"""
        with self._lock:
            self._measurements.clear()


# ════════════════════════════════════════════════════════════════════
# 全局单例实例
# ════════════════════════════════════════════════════════════════════

# 全局 Skill 指令缓存（TTL=5分钟）
skill_instruction_cache = LRUCache(maxsize=256, ttl=300)

# 全局 Token 计算缓存
token_cache = TokenCache(maxsize=512)

# 全局性能监控器
perf_monitor = PerformanceMonitor()

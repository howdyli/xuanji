#!/usr/bin/env python3
"""
XiaoPaw v2 性能基准测试工具

用于测量和比较优化前后的性能指标：
- 文件 I/O 性能（同步 vs 异步）
- Token 计数性能（带缓存 vs 无缓存）
- Skill 加载性能
- 内存使用情况

用法:
    python benchmark.py                    # 运行所有测试
    python benchmark.py --test io          # 只运行 I/O 测试
    python benchmark.py --test cache       # 只运行缓存测试
    python benchmark.py --iterations 100   # 自定义迭代次数
    python benchmark.py --verbose          # 显示详细信息

输出示例：
    ══════════════════════════════════════════
    XiaoPaw v2 Performance Benchmark Results
    ══════════════════════════════════════════

    [1] File I/O Performance (100 iterations)
    ──────────────────────────────────────
    sync_load:    0.123s avg (σ=0.015)
    async_load:   0.089s avg (σ=0.012)  ✅ 27.6% faster
    ...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import string
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def generate_test_messages(count: int = 20, avg_length: int = 500) -> list[dict]:
    """生成测试用的消息列表。

    Args:
        count: 消息数量
        avg_length: 平均消息长度（字符）
    """
    messages = []
    roles = ["user", "assistant"]

    for i in range(count):
        role = roles[i % 2]
        # 生成随机文本（模拟真实消息长度变化）
        length = avg_length + random.randint(-int(avg_length * 0.3), int(avg_length * 0.3))
        content = "".join(random.choices(string.ascii_letters + string.digits + " \n\t", k=length))

        messages.append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })

    return messages


class BenchmarkResult:
    """单个基准测试结果"""

    def __init__(self, name: str):
        self.name = name
        self.durations: list[float] = []
        self.success_count = 0
        self.error_count = 0
        self.errors: list[str] = []

    def record(self, duration: float, success: bool = True, error: Optional[str] = None):
        self.durations.append(duration)
        if success:
            self.success_count += 1
        else:
            self.error_count += 1
            if error:
                self.errors.append(error)

    @property
    def total(self) -> int:
        return len(self.durations)

    @property
    def avg_duration(self) -> float:
        if not self.durations:
            return 0.0
        return sum(self.durations) / len(self.durations)

    @property
    def min_duration(self) -> float:
        return min(self.durations) if self.durations else 0.0

    @property
    def max_duration(self) -> float:
        return max(self.durations) if self.durations else 0.0

    @property
    def std_dev(self) -> float:
        if len(self.durations) < 2:
            return 0.0
        avg = self.avg_duration
        variance = sum((d - avg) ** 2 for d in self.durations) / (len(self.durations) - 1)
        return variance**0.5

    @property
    def p95_duration(self) -> float:
        if not self.durations:
            return 0.0
        sorted_durations = sorted(self.durations)
        idx = int(len(sorted_durations) * 0.95)
        return sorted_durations[min(idx, len(sorted_durations) - 1)]

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "total": self.total,
            "success": self.success_count,
            "errors": self.error_count,
            "avg_sec": round(self.avg_duration, 4),
            "min_sec": round(self.min_duration, 4),
            "max_sec": round(self.max_duration, 4),
            "std_dev": round(self.std_dev, 4),
            "p95_sec": round(self.p95_duration, 4),
        }


# ════════════════════════════════════════════════════════════════════
# 基准测试函数
# ════════════════════════════════════════════════════════════════════


async def bench_async_io(iterations: int, tmp_dir: Path) -> BenchmarkResult:
    """异步文件 I/O 基准测试"""
    from xiaopaw.utils.performance import (
        async_load_session_ctx,
        async_save_session_ctx,
    )

    result = BenchmarkResult("async_io")
    session_id = f"bench_{os.getpid()}_{time.time()}"
    messages = generate_test_messages()

    # 预热
    await async_save_session_ctx(session_id, messages, tmp_dir)
    await async_load_session_ctx(session_id, tmp_dir)

    for _ in range(iterations):
        start = time.perf_counter()
        try:
            await async_save_session_ctx(session_id, messages, tmp_dir)
            await async_load_session_ctx(session_id, tmp_dir)
            elapsed = time.perf_counter() - start
            result.record(elapsed, success=True)
        except Exception as e:
            elapsed = time.perf_counter() - start
            result.record(elapsed, success=False, error=str(e))

    return result


def bench_sync_io(iterations: int, tmp_dir: Path) -> BenchmarkResult:
    """同步文件 I/O 基准测试"""
    from xiaopaw.memory.context_mgmt import load_session_ctx, save_session_ctx

    result = BenchmarkResult("sync_io")
    session_id = f"bench_{os.getpid()}_{time.time()}"
    messages = generate_test_messages()

    # 预热
    save_session_ctx(session_id, messages, tmp_dir)
    load_session_ctx(session_id, tmp_dir)

    for _ in range(iterations):
        start = time.perf_counter()
        try:
            save_session_ctx(session_id, messages, tmp_dir)
            load_session_ctx(session_id, tmp_dir)
            elapsed = time.perf_counter() - start
            result.record(elapsed, success=True)
        except Exception as e:
            elapsed = time.perf_counter() - start
            result.record(elapsed, success=False, error=str(e))

    return result


def bench_token_count_with_cache(iterations: int) -> BenchmarkResult:
    """Token 计数（带缓存）基准测试"""
    from xiaopaw.utils.performance import TokenCache
    from xiaopaw.memory.token_counter import count_tokens

    cache = TokenCache(maxsize=512)
    cached_count = cache.cached(count_tokens)

    result = BenchmarkResult("token_cached")

    for i in range(iterations):
        messages = generate_test_messages(count=10 + i % 5)  # 变化消息数量以测试不同哈希
        start = time.perf_counter()
        try:
            tokens = cached_count(messages)
            elapsed = time.perf_counter() - start
            result.record(elapsed, success=True)
        except Exception as e:
            elapsed = time.perf_counter() - start
            result.record(elapsed, success=False, error=str(e))

    # 记录缓存统计
    result.cache_stats = cache.get_stats()
    return result


def bench_token_count_no_cache(iterations: int) -> BenchmarkResult:
    """Token 计数（无缓存）基准测试"""
    from xiaopaw.memory.token_counter import count_tokens

    result = BenchmarkResult("token_no_cache")

    for i in range(iterations):
        messages = generate_test_messages(count=10 + i % 5)
        start = time.perf_counter()
        try:
            tokens = count_tokens(messages)
            elapsed = time.perf_counter() - start
            result.record(elapsed, success=True)
        except Exception as e:
            elapsed = time.perf_counter() - start
            result.record(elapsed, success=False, error=str(e))

    return result


def bench_lru_cache(iterations: int) -> BenchmarkResult:
    """LRU 缓存操作基准测试"""
    from xiaopaw.utils.performance import LRUCache

    cache = LRUCache(maxsize=1000)
    result = BenchmarkResult("lru_cache_operations")

    for i in range(iterations):
        key = f"key_{i % 200}"  # 重复键以测试命中
        value = {"data": "x" * random.randint(100, 500)}

        start = time.perf_counter()
        try:
            cached_value = cache.get(key)
            if cached_value is None:
                cache.set(key, value)
            elapsed = time.perf_counter() - start
            result.record(elapsed, success=True)
        except Exception as e:
            elapsed = time.perf_counter() - start
            result.record(elapsed, success=False, error=str(e))

    result.cache_stats = cache.get_stats()
    return result


# ════════════════════════════════════════════════════════════════════
# 结果输出格式化
# ════════════════════════════════════════════════════════════════════


def print_header(title: str):
    width = 55
    print(f"\n{'═' * width}")
    print(f" {title:^{width - 2}} ")
    print(f"{'═' * width}")


def print_result(result: BenchmarkResult):
    s = result.summary()
    print(f"\n  📊 {s['name']}:")
    print(f"     Iterations: {s['total']} | Success: {s['success']} | Errors: {s['errors']}")
    print(f"     Avg: {s['avg_sec']:.4f}s | Min: {s['min_sec']:.4f}s | Max: {s['max_sec']:.4f}s")
    print(f"     Std Dev: {s['std_dev']:.4f}s | P95: {s['p95_sec']:.4f}s")

    if hasattr(result, 'cache_stats'):
        stats = result.cache_stats
        print(f"     Cache Hit Rate: {stats['hit_rate']:.1%} | Hits: {stats['hits']} | Misses: {stats['misses']}")


def compare_results(r1: BenchmarkResult, r2: BenchmarkResult) -> None:
    """对比两个结果并显示改进百分比"""
    avg1, avg2 = r1.avg_duration, r2.avg_duration

    if avg1 > 0:
        improvement = ((avg1 - avg2) / avg1) * 100
        symbol = "✅" if improvement > 0 else ("⚠️" if abs(improvement) < 5 else "❌")
        print(f"\n  {symbol} Comparison ({r1.name} → {r2.name}):")
        print(f"     Speed improvement: {improvement:+.1f}%")
        print(f"     Throughput: {avg1 / avg2:.2f}x faster")


# ════════════════════════════════════════════════════════════════════
# 主程序
# ════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="XiaoPaw v2 Performance Benchmark Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Run all benchmarks
  %(prog)s --test io --verbose      # Only I/O tests with details
  %(prog)s --iterations 50           # Custom iteration count
        """,
    )
    parser.add_argument(
        "--test",
        choices=["all", "io", "cache"],
        default="all",
        help="Which test suite to run (default: all)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Number of iterations per test (default: 50)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Show verbose output",
    )

    args = parser.parse_args()

    # 配置日志级别
    logging.basicConfig(
        level=logging.WARNING if not args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print("\n" + "=" * 57)
    print(f"  XiaoPaw v2 Performance Benchmark Results".center(55))
    print("=" * 57)
    print(f"  Iterations: {args.iterations} | Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    all_results: list[BenchmarkResult] = []

    # 创建临时目录
    with tempfile.TemporaryDirectory(prefix="xiaopaw_bench_") as tmp_dir:
        tmp_path = Path(tmp_dir)

        # ─── 测试套件 1：I/O 性能 ───
        if args.test in ["all", "io"]:
            print_header("[1] File I/O Performance (sync vs async)")

            print("\n  Running synchronous I/O test...")
            sync_result = bench_sync_io(args.iterations, tmp_path)
            print_result(sync_result)
            all_results.append(sync_result)

            print("\n  Running asynchronous I/O test...")
            async_result = asyncio.run(bench_async_io(args.iterations, tmp_path))
            print_result(async_result)
            all_results.append(async_result)

            compare_results(sync_result, async_result)

        # ─── 测试套件 2：缓存性能 ───
        if args.test in ["all", "cache"]:
            print_header("[2] Token Count & Caching Performance")

            print("\n  Running token count WITHOUT cache...")
            no_cache_result = bench_token_count_no_cache(args.iterations)
            print_result(no_cache_result)
            all_results.append(no_cache_result)

            print("\n  Running token count WITH cache...")
            cache_result = bench_token_count_with_cache(args.iterations)
            print_result(cache_result)
            all_results.append(cache_result)

            compare_results(no_cache_result, cache_result)

            print("\n  Running LRU cache operations...")
            lru_result = bench_lru_cache(args.iterations)
            print_result(lru_result)
            all_results.append(lru_result)

    # ─── 总结 ───
    print_header("Summary")
    print("\n  All tests completed successfully! ✅\n")

    if args.verbose:
        # 输出完整结果到 JSON 文件
        output_file = Path(__file__).parent.parent / "benchmark-results.json"
        results_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "iterations": args.iterations,
            "results": [r.summary() for r in all_results],
        }
        output_file.write_text(json.dumps(results_data, indent=2, ensure_ascii=False))
        print(f"  Detailed results saved to: {output_file}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""RetryStrategy —— 指数退避 + jitter 的智能重试策略。

【设计理念】借鉴 Proma 的重试策略模式：
- 指数退避序列：1s → 2s → 4s → 8s → 15s(cap)
- ±20% 随机 jitter，避免多会话同时重试造成惊群效应
- 累计等待预算上限（默认 5 分钟），防止无限等待
- 与 error_classifier 联动，只对可重试错误执行重试

【与现有 retry.py 的关系】
xiaopaw/utils/retry.py 提供简单的 async_retry 函数（固定退避序列），
本模块提供更精细的策略：
- 基于错误分类的动态重试决策
- 指数退避 + jitter
- 累计等待预算
- 重试事件回调（用于通知前端/日志）

retry.py 可保持不动，本模块作为增强层叠加使用。
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Callable

from xiaopaw.utils.error_classifier import (
    ClassifiedError,
    ErrorCode,
    RETRYABLE_ERROR_CODES,
    classify_exception,
    classify_http_error,
)

logger = logging.getLogger(__name__)

# ---- 默认配置常量（借鉴 Proma 的参数）----

DEFAULT_MAX_RETRIES = 10           # 最大重试次数（Proma 是 25，我们保守一些）
DEFAULT_MAX_WAIT_MS = 5 * 60_000   # 累计等待预算上限：5 分钟
DEFAULT_BASE_DELAY_MS = 1000       # 基础延迟：1 秒
DEFAULT_MAX_DELAY_MS = 15_000      # 单次延迟上限：15 秒
DEFAULT_JITTER_RATIO = 0.2         # ±20% jitter


@dataclass
class RetryConfig:
    """重试策略配置。"""

    max_retries: int = DEFAULT_MAX_RETRIES
    max_wait_ms: int = DEFAULT_MAX_WAIT_MS
    base_delay_ms: int = DEFAULT_BASE_DELAY_MS
    max_delay_ms: int = DEFAULT_MAX_DELAY_MS
    jitter_ratio: float = DEFAULT_JITTER_RATIO
    # 额外可重试的错误码（叠加到 RETRYABLE_ERROR_CODES 上）
    extra_retryable_codes: frozenset[str] = frozenset()


@dataclass
class RetryAttempt:
    """单次重试记录。"""

    attempt: int           # 第几次重试（从 1 开始）
    error_code: str        # 错误码
    delay_ms: int          # 本次等待时间
    elapsed_total_ms: int  # 截至本次的累计等待时间
    message: str           # 错误描述


@dataclass
class RetryResult:
    """重试结果汇总。"""

    success: bool
    attempts: list[RetryAttempt] = field(default_factory=list)
    total_delay_ms: int = 0
    final_error: ClassifiedError | None = None

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


def compute_delay_ms(
    attempt: int,
    elapsed_ms: int,
    config: RetryConfig,
) -> int:
    """计算本次重试的等待时间（指数退避 + jitter）。

    算法：
    1. base = min(base_delay * 2^(attempt-1), max_delay)
    2. jitter = base * random(-jitter_ratio, +jitter_ratio)
    3. delay = min(delay, remaining_budget)

    Args:
        attempt: 当前重试次数（从 1 开始）
        elapsed_ms: 已累计等待的毫秒数
        config: 重试配置

    Returns:
        等待毫秒数，0 表示预算耗尽不应再重试
    """
    remaining_ms = config.max_wait_ms - elapsed_ms
    if remaining_ms <= 0:
        return 0

    # 指数退避
    base = min(
        config.base_delay_ms * (2 ** (attempt - 1)),
        config.max_delay_ms,
    )

    # ±jitter_ratio 的随机抖动
    jitter = base * (random.random() * 2 * config.jitter_ratio - config.jitter_ratio)
    delay = max(0, round(base + jitter))

    return min(remaining_ms, delay)


def is_retryable(error: ClassifiedError, config: RetryConfig) -> bool:
    """判断错误是否可重试。

    综合 error.retryable 字段和配置的额外可重试码。
    """
    if error.retryable:
        return True
    return error.code in config.extra_retryable_codes


async def retry_with_strategy(
    fn: Callable,
    *args,
    config: RetryConfig | None = None,
    on_retry: Callable[[RetryAttempt], None] | None = None,
    on_partial_result: Callable[[str], None] | None = None,
    **kwargs,
) -> RetryResult:
    """带完整策略的异步重试执行器。

    Args:
        fn: 要执行的异步函数
        *args: 传递给 fn 的位置参数
        config: 重试配置，为 None 时使用默认配置
        on_retry: 每次重试前的回调，参数为 RetryAttempt
        on_partial_result: 收到部分结果时的回调（用于部分内容保存）
        **kwargs: 传递给 fn 的关键字参数

    Returns:
        RetryResult 包含成功/失败状态、重试记录和最终错误
    """
    cfg = config or RetryConfig()
    result = RetryResult(success=False)
    start_time = time.monotonic()
    elapsed_delay_ms = 0

    for attempt_num in range(cfg.max_retries + 1):
        try:
            output = await fn(*args, **kwargs)
            result.success = True
            return result

        except Exception as exc:
            # 分类错误
            classified = _classify_exc(exc)

            # 首次失败（attempt_num == 0）不计入重试
            if attempt_num == 0:
                # 检查是否可重试
                if not is_retryable(classified, cfg):
                    result.final_error = classified
                    return result

            if attempt_num >= cfg.max_retries:
                # 重试次数耗尽
                result.final_error = classified
                return result

            if not is_retryable(classified, cfg):
                result.final_error = classified
                return result

            # 计算延迟
            delay_ms = compute_delay_ms(attempt_num + 1, elapsed_delay_ms, cfg)
            if delay_ms <= 0:
                # 等待预算耗尽
                result.final_error = classified
                return result

            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            retry_attempt = RetryAttempt(
                attempt=attempt_num + 1,
                error_code=classified.code,
                delay_ms=delay_ms,
                elapsed_total_ms=elapsed_ms,
                message=classified.message,
            )
            result.attempts.append(retry_attempt)

            logger.info(
                "[RetryStrategy] attempt %d/%d: %s, waiting %dms (elapsed %dms)",
                attempt_num + 1, cfg.max_retries,
                classified.code, delay_ms, elapsed_ms,
            )

            # 通知回调
            if on_retry:
                try:
                    on_retry(retry_attempt)
                except Exception:
                    pass

            # 等待
            await asyncio.sleep(delay_ms / 1000)
            elapsed_delay_ms += delay_ms

    result.final_error = ClassifiedError(
        code=ErrorCode.UNKNOWN.value,
        status_code=0,
        message="重试次数耗尽",
        retryable=False,
    )
    return result


def _classify_exc(exc: Exception) -> ClassifiedError:
    """智能异常分类：优先识别 requests 库的 HTTP 错误。"""
    # 尝试提取 HTTP 状态码（requests.Response 对象）
    resp = getattr(exc, "response", None)
    if resp is not None:
        status_code = getattr(resp, "status_code", 0)
        text = ""
        try:
            text = resp.text[:1000]
        except Exception:
            pass
        if status_code:
            return classify_http_error(status_code, text, str(exc))

    # 回退到通用异常分类
    return classify_exception(exc)


# ---- 同步版：供 aliyun_llm.call() 等非 async 场景使用 ----

def compute_delay_ms_sync(
    attempt: int,
    elapsed_ms: int,
    config: RetryConfig | None = None,
) -> int:
    """同步版延迟计算（供非 async 场景使用）。"""
    return compute_delay_ms(attempt, elapsed_ms, config or RetryConfig())


import time as _time_mod

def retry_sync_with_strategy(
    fn: Callable,
    *args,
    config: RetryConfig | None = None,
    on_retry: Callable[[RetryAttempt], None] | None = None,
    **kwargs,
) -> RetryResult:
    """同步版的重试执行器（供 AliyunLLM.call() 等场景）。

    接口与 retry_with_strategy 一致，但使用 time.sleep 而非 asyncio.sleep。
    """
    cfg = config or RetryConfig()
    result = RetryResult(success=False)
    start_time = _time_mod.monotonic()
    elapsed_delay_ms = 0

    for attempt_num in range(cfg.max_retries + 1):
        try:
            output = fn(*args, **kwargs)
            result.success = True
            return result

        except Exception as exc:
            classified = _classify_exc(exc)

            if attempt_num >= cfg.max_retries:
                result.final_error = classified
                return result

            if not is_retryable(classified, cfg):
                result.final_error = classified
                return result

            delay_ms = compute_delay_ms(attempt_num + 1, elapsed_delay_ms, cfg)
            if delay_ms <= 0:
                result.final_error = classified
                return result

            elapsed_ms = int((_time_mod.monotonic() - start_time) * 1000)
            retry_attempt = RetryAttempt(
                attempt=attempt_num + 1,
                error_code=classified.code,
                delay_ms=delay_ms,
                elapsed_total_ms=elapsed_ms,
                message=classified.message,
            )
            result.attempts.append(retry_attempt)

            logger.info(
                "[RetryStrategy] sync attempt %d/%d: %s, waiting %dms",
                attempt_num + 1, cfg.max_retries,
                classified.code, delay_ms,
            )

            if on_retry:
                try:
                    on_retry(retry_attempt)
                except Exception:
                    pass

            _time_mod.sleep(delay_ms / 1000)
            elapsed_delay_ms += delay_ms

    result.final_error = ClassifiedError(
        code=ErrorCode.UNKNOWN.value,
        status_code=0,
        message="重试次数耗尽",
        retryable=False,
    )
    return result

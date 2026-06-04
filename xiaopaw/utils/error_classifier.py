"""ErrorClassifier —— LLM/HTTP 错误分类体系。

【设计理念】借鉴 Proma 的错误分类模式，将 LLM 调用中的错误归类为标准错误码，
供 retry_strategy 决策是否重试、如何退避。

【错误码体系】
- rate_limited    : HTTP 429，API 限流，通常很快恢复
- provider_error  : HTTP 5xx / 529（Anthropic 过载），服务端故障
- service_error   : HTTP 502/503/504，网关/服务不可用
- network_error   : 连接重置、超时、DNS 解析失败等瞬时网络故障
- auth_error      : HTTP 401/403，认证/授权失败（不可重试）
- quota_exceeded  : HTTP 402/429 + 余额不足语义，需充值（不可重试）
- invalid_request : HTTP 400，请求格式错误（不可重试）
- context_overflow: HTTP 400 + token 超限语义，需截断上下文（不可重试）
- session_not_found: SDK session 过期或被清理（可恢复）
- unknown         : 无法归类的错误

【与 retry_tracker 的协作】
error_classifier 负责"分类"，retry_strategy 负责"决策"，
retry_tracker 负责"观测/统计"——三者各司其职。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ErrorCode(str, Enum):
    """标准错误码枚举。"""

    RATE_LIMITED = "rate_limited"
    PROVIDER_ERROR = "provider_error"
    SERVICE_ERROR = "service_error"
    NETWORK_ERROR = "network_error"
    AUTH_ERROR = "auth_error"
    QUOTA_EXCEEDED = "quota_exceeded"
    INVALID_REQUEST = "invalid_request"
    CONTEXT_OVERFLOW = "context_overflow"
    SESSION_NOT_FOUND = "session_not_found"
    UNKNOWN = "unknown"


# 可自动重试的错误码集合
RETRYABLE_ERROR_CODES: frozenset[str] = frozenset({
    ErrorCode.RATE_LIMITED.value,
    ErrorCode.PROVIDER_ERROR.value,
    ErrorCode.SERVICE_ERROR.value,
    ErrorCode.NETWORK_ERROR.value,
})

# 不可重试的错误码（需要人工介入）
NON_RETRYABLE_ERROR_CODES: frozenset[str] = frozenset({
    ErrorCode.AUTH_ERROR.value,
    ErrorCode.QUOTA_EXCEEDED.value,
    ErrorCode.INVALID_REQUEST.value,
    ErrorCode.CONTEXT_OVERFLOW.value,
})


@dataclass(frozen=True)
class ClassifiedError:
    """分类后的错误信息。"""

    code: str           # ErrorCode.value
    status_code: int    # HTTP 状态码，0 表示非 HTTP 错误
    message: str        # 人类可读的错误描述
    retryable: bool     # 是否可自动重试
    original: Exception | None = None  # 原始异常（可选）

    @property
    def is_rate_limited(self) -> bool:
        return self.code == ErrorCode.RATE_LIMITED.value

    @property
    def is_quota_exceeded(self) -> bool:
        return self.code == ErrorCode.QUOTA_EXCEEDED.value

    @property
    def is_context_overflow(self) -> bool:
        return self.code == ErrorCode.CONTEXT_OVERFLOW.value

    def __str__(self) -> str:
        return f"[{self.code}] HTTP {self.status_code}: {self.message}"


# ---- 瞬时网络错误关键词 ----
_NETWORK_ERROR_PATTERNS = (
    re.compile(r"ECONNRESET", re.I),
    re.compile(r"ECONNREFUSED", re.I),
    re.compile(r"ENOTFOUND", re.I),
    re.compile(r"ETIMEDOUT", re.I),
    re.compile(r"socket hang up", re.I),
    re.compile(r"Connection (?:aborted|reset|refused)", re.I),
    re.compile(r"RemoteDisconnected", re.I),
    re.compile(r"TimeoutError", re.I),
    re.compile(r"ReadTimeout", re.I),
    re.compile(r"ConnectTimeout", re.I),
    re.compile(r"NewConnectionError", re.I),
    re.compile(r"Max retries exceeded", re.I),
)

# ---- 上下文溢出关键词 ----
_CONTEXT_OVERFLOW_PATTERNS = (
    re.compile(r"token.*(?:maximum|limit|exceed)", re.I),
    re.compile(r"context.*(?:length|window|size).*(?:exceed|too long)", re.I),
    re.compile(r"prompt.*too.*long", re.I),
    re.compile(r"max_tokens", re.I),
    re.compile(r"reduce.*(?:input|prompt|context)", re.I),
)

# ---- 余额不足关键词 ----
_QUOTA_PATTERNS = (
    re.compile(r"insufficient.*(?:balance|quota|funds|credit)", re.I),
    re.compile(r"balance.*(?:not enough|insufficient)", re.I),
    re.compile(r"余额不足", re.I),
    re.compile(r"quota.*exceeded", re.I),
    re.compile(r"billing", re.I),
)

# ---- Session 不存在关键词 ----
_SESSION_NOT_FOUND_PATTERNS = (
    re.compile(r"No conversation found.*session", re.I),
    re.compile(r"session.*(?:not found|expired|invalid)", re.I),
)


def classify_http_error(
    status_code: int,
    response_text: str = "",
    error_message: str = "",
) -> ClassifiedError:
    """根据 HTTP 状态码和响应内容分类错误。

    Args:
        status_code: HTTP 响应状态码
        response_text: 响应体文本（用于语义分析）
        error_message: 额外错误信息

    Returns:
        ClassifiedError 实例
    """
    combined_text = f"{response_text} {error_message}"

    # 4xx 客户端错误
    if status_code == 429:
        # 429 可能是限流（可重试）也可能是余额不足（不可重试）
        if any(p.search(combined_text) for p in _QUOTA_PATTERNS):
            return ClassifiedError(
                code=ErrorCode.QUOTA_EXCEEDED.value,
                status_code=status_code,
                message="API 余额不足，请充值",
                retryable=False,
            )
        return ClassifiedError(
            code=ErrorCode.RATE_LIMITED.value,
            status_code=status_code,
            message="API 请求频率受限",
            retryable=True,
        )

    if status_code == 401 or status_code == 403:
        return ClassifiedError(
            code=ErrorCode.AUTH_ERROR.value,
            status_code=status_code,
            message=f"认证/授权失败 (HTTP {status_code})",
            retryable=False,
        )

    if status_code == 402:
        return ClassifiedError(
            code=ErrorCode.QUOTA_EXCEEDED.value,
            status_code=status_code,
            message="API 余额不足 (HTTP 402)",
            retryable=False,
        )

    if status_code == 400:
        # 400 需要语义分析：可能是上下文溢出
        if any(p.search(combined_text) for p in _CONTEXT_OVERFLOW_PATTERNS):
            return ClassifiedError(
                code=ErrorCode.CONTEXT_OVERFLOW.value,
                status_code=status_code,
                message="上下文长度超出模型限制",
                retryable=False,
            )
        return ClassifiedError(
            code=ErrorCode.INVALID_REQUEST.value,
            status_code=status_code,
            message=f"请求格式错误 (HTTP 400): {error_message[:200]}",
            retryable=False,
        )

    # 5xx 服务端错误
    if status_code == 529:
        return ClassifiedError(
            code=ErrorCode.PROVIDER_ERROR.value,
            status_code=status_code,
            message="AI 服务过载 (HTTP 529)",
            retryable=True,
        )

    if status_code in (502, 503, 504):
        return ClassifiedError(
            code=ErrorCode.SERVICE_ERROR.value,
            status_code=status_code,
            message=f"服务不可用 (HTTP {status_code})",
            retryable=True,
        )

    if status_code >= 500:
        return ClassifiedError(
            code=ErrorCode.PROVIDER_ERROR.value,
            status_code=status_code,
            message=f"服务端错误 (HTTP {status_code})",
            retryable=True,
        )

    return ClassifiedError(
        code=ErrorCode.UNKNOWN.value,
        status_code=status_code,
        message=f"未分类 HTTP 错误 (HTTP {status_code})",
        retryable=False,
    )


def classify_exception(exc: Exception) -> ClassifiedError:
    """根据异常类型分类。

    Args:
        exc: 捕获的异常实例

    Returns:
        ClassifiedError 实例
    """
    exc_str = str(exc)
    exc_type = type(exc).__name__

    # 超时类
    if exc_type in ("TimeoutError", "Timeout", "ReadTimeout", "ConnectTimeout"):
        return ClassifiedError(
            code=ErrorCode.NETWORK_ERROR.value,
            status_code=0,
            message=f"连接超时: {exc_str[:200]}",
            retryable=True,
            original=exc,
        )

    # 连接类
    if exc_type in (
        "ConnectionError", "ConnectionResetError", "ConnectionRefusedError",
        "ConnectionAbortedError", "BrokenPipeError",
    ):
        return ClassifiedError(
            code=ErrorCode.NETWORK_ERROR.value,
            status_code=0,
            message=f"连接错误: {exc_str[:200]}",
            retryable=True,
            original=exc,
        )

    # requests 库异常
    if exc_type in ("RequestException", "ConnectionError", "HTTPError"):
        # 进一步分析文本
        if any(p.search(exc_str) for p in _NETWORK_ERROR_PATTERNS):
            return ClassifiedError(
                code=ErrorCode.NETWORK_ERROR.value,
                status_code=0,
                message=f"网络错误: {exc_str[:200]}",
                retryable=True,
                original=exc,
            )

    # Session 不存在
    if any(p.search(exc_str) for p in _SESSION_NOT_FOUND_PATTERNS):
        return ClassifiedError(
            code=ErrorCode.SESSION_NOT_FOUND.value,
            status_code=0,
            message=f"会话不存在或已过期: {exc_str[:200]}",
            retryable=False,  # 不可直接重试，但可通过上下文回填恢复
            original=exc,
        )

    # 通用网络模式匹配
    if any(p.search(exc_str) for p in _NETWORK_ERROR_PATTERNS):
        return ClassifiedError(
            code=ErrorCode.NETWORK_ERROR.value,
            status_code=0,
            message=f"网络异常: {exc_str[:200]}",
            retryable=True,
            original=exc,
        )

    return ClassifiedError(
        code=ErrorCode.UNKNOWN.value,
        status_code=0,
        message=f"{exc_type}: {exc_str[:200]}",
        retryable=False,
        original=exc,
    )


def is_transient_network_error(text: str) -> bool:
    """判断给定文本是否包含瞬时网络错误特征。

    与 Proma 的 isTransientNetworkError 对齐：
    识别 ECONNRESET / socket hang up / terminated 等模式。
    """
    return any(p.search(text) for p in _NETWORK_ERROR_PATTERNS)

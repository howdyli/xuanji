"""Markdown builder for session export."""

from __future__ import annotations

import re
from datetime import datetime


def _format_timestamp(ts_ms: int) -> str:
    """Unix 毫秒时间戳 → YYYY-MM-DD HH:MM"""
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M")


def _format_error_message(content: str) -> str:
    """[ERROR_DISPLAY:type:message] → > ⚠️ 错误: message"""
    m = re.match(r"^\[ERROR_DISPLAY:[^:]+:(.+)\]$", content)
    msg = m.group(1) if m else content
    return f"> ⚠️ 错误: {msg}"


def _is_cron_message(feishu_msg_id: str | None) -> bool:
    """检查是否为定时任务消息（feishu_msg_id 以 cron_ 开头）"""
    return bool(feishu_msg_id and feishu_msg_id.startswith("cron_"))


_ROLE_EMOJI = {"user": "👤", "assistant": "🤖"}


def build_session_markdown(
    title: str,
    session_id: str,
    created_at: str,
    messages: list[dict],
    include_metadata: bool = True,
) -> str:
    """将会话消息列表转换为结构化 Markdown 文本。

    Parameters
    ----------
    title : 会话标题
    session_id : 会话唯一 ID
    created_at : 创建时间（已格式化的字符串）
    messages : 消息列表，每条包含 role / content / ts / feishu_msg_id
    include_metadata : 是否在顶部显示元数据摘要
    """
    parts: list[str] = []

    # ── 标题 ──
    parts.append(f"# {title}")

    # ── 元数据 ──
    if include_metadata:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        count = len(messages)
        parts.append(
            f"> **会话ID**: {session_id} | "
            f"**创建时间**: {created_at} | "
            f"**消息数**: {count} | "
            f"**导出时间**: {now}"
        )

    parts.append("---")

    # ── 消息体 ──
    for msg in messages:
        role: str = msg.get("role", "unknown")
        content: str = msg.get("content", "")
        ts: int = msg.get("ts", 0)
        feishu_msg_id: str | None = msg.get("feishu_msg_id")

        emoji = _ROLE_EMOJI.get(role, "❓")
        ts_str = _format_timestamp(ts) if ts else "未知时间"

        # 定时任务标注
        cron_tag = "（定时任务触发）" if _is_cron_message(feishu_msg_id) else ""

        parts.append(f"## {emoji} {role.capitalize()}{cron_tag} · {ts_str}")

        # 错误消息特殊处理
        if content.startswith("[ERROR_DISPLAY:"):
            parts.append(_format_error_message(content))
        else:
            parts.append(content)

        parts.append("---")

    # ── 页脚 ──
    parts.append("*由「玄机」AI 工作台生成*")

    return "\n\n".join(parts)

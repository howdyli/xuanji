"""ContextBuilder —— 上下文回填与 Session 恢复。

【设计理念】借鉴 Proma 的上下文管理策略：
- 滑动窗口：只保留最近 N 条消息，避免上下文溢出
- 工具摘要：从 assistant 消息中提取工具调用摘要，压缩历史信息
- Session 恢复：当 Agent 连接断开后，注入历史路径让 LLM 自行读取恢复
- 跨会话引用：支持用户引用其他会话的上下文

【与 SessionManager 的关系】
SessionManager 负责 JSONL 持久化和索引管理，
ContextBuilder 负责"把历史变成 prompt"——
它是 SessionManager.load_history() 和 agent_fn() 之间的桥梁。

【使用方式】
    builder = ContextBuilder(session_mgr, max_messages=20)
    context_prompt = await builder.build_context(
        session_id=session_id,
        user_message="用户的新消息",
    )
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from xiaopaw.session.models import MessageEntry

logger = logging.getLogger(__name__)

# ---- 配置常量 ----

DEFAULT_MAX_MESSAGES = 20        # 滑动窗口：最近 20 条消息
DEFAULT_MAX_TOOL_SUMMARY = 200   # 单条工具摘要最大字符数
DEFAULT_MAX_CONTEXT_CHARS = 8000  # 上下文总字符预算


@dataclass
class ToolCallSummary:
    """从 assistant 消息中提取的工具调用摘要。"""

    tool_name: str
    key_param: str  # 关键参数（如 file_path / command / query）
    truncated: bool = False

    def format(self) -> str:
        param = self.key_param[:80] if self.key_param else ""
        suffix = "..." if self.truncated else ""
        return f"[tool: {self.tool_name}: {param}{suffix}]"


def extract_tool_summaries(content: str) -> list[ToolCallSummary]:
    """从 assistant 消息内容中提取工具调用摘要。

    识别常见的工具调用模式：
    - [Tool: tool_name] 格式
    - skill_loader 调用
    - 文件操作路径

    这是一个启发式提取器，不依赖特定的消息格式。
    """
    summaries: list[ToolCallSummary] = []

    # 模式 1：[Tool: xxx] 或 [tool: xxx]
    tool_pattern = re.compile(r"\[Tool:\s*(\w+)\]", re.I)
    for m in tool_pattern.finditer(content):
        summaries.append(ToolCallSummary(tool_name=m.group(1), key_param=""))

    # 模式 2：文件路径引用
    file_pattern = re.compile(r"(?:read|write|edit|open)\s+(?:file\s+)?([/\w.-]+(?:\.\w+)+)")
    for m in file_pattern.finditer(content[:1000]):
        path = m.group(1)
        summaries.append(ToolCallSummary(
            tool_name="file_operation",
            key_param=path,
            truncated=len(path) > 80,
        ))

    # 模式 3：skill 调用
    skill_pattern = re.compile(r"(?:skill|技能)\s*[:(]\s*(\w+)", re.I)
    for m in skill_pattern.finditer(content[:1000]):
        summaries.append(ToolCallSummary(tool_name="skill", key_param=m.group(1)))

    return summaries


def format_message_line(msg: MessageEntry, include_tool_summary: bool = True) -> str | None:
    """将单条消息格式化为上下文行。

    Args:
        msg: 消息条目
        include_tool_summary: 是否为 assistant 消息附加工具摘要

    Returns:
        格式化后的行文本，None 表示跳过（空内容）
    """
    content = msg.content.strip()
    if not content:
        return None

    # 截断过长的消息
    if len(content) > 500:
        content = content[:500] + "...[truncated]"

    line = f"[{msg.role}]: {content}"

    # assistant 消息附加工具摘要
    if include_tool_summary and msg.role == "assistant":
        summaries = extract_tool_summaries(msg.content)
        if summaries:
            summary_strs = [s.format() for s in summaries[:5]]  # 最多 5 个摘要
            line += f"\n  工具活动: {' '.join(summary_strs)}"

    return line


class ContextBuilder:
    """上下文构建器 —— 将 session 历史转化为 LLM 可消费的 prompt 片段。

    核心方法：
    - build_context(): 构建完整的上下文回填 prompt
    - build_recovery_prompt(): 构建 session 恢复 prompt
    - build_cross_session_ref(): 构建跨会话引用
    """

    def __init__(
        self,
        sessions_dir: Path | str = "data/sessions",
        max_messages: int = DEFAULT_MAX_MESSAGES,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    ) -> None:
        self._sessions_dir = Path(sessions_dir)
        self._max_messages = max_messages
        self._max_context_chars = max_context_chars

    def build_context_from_history(
        self,
        history: list[MessageEntry],
        user_message: str,
        session_id: str = "",
    ) -> str:
        """从历史消息列表构建上下文回填 prompt。

        这是最常用的入口：runner 调用 load_history() 后，
        把结果传给本方法，获得包含历史上下文的完整 prompt。

        Args:
            history: 历史消息列表（来自 SessionManager.load_history）
            user_message: 当前用户消息
            session_id: 会话 ID（用于元信息注入）

        Returns:
            包含历史上下文的完整 prompt 字符串
        """
        if not history:
            return user_message

        # 取最近 N 条
        recent = history[-self._max_messages:]

        lines: list[str] = []
        total_chars = 0
        for msg in recent:
            line = format_message_line(msg)
            if line is None:
                continue
            if total_chars + len(line) > self._max_context_chars:
                break
            lines.append(line)
            total_chars += len(line)

        if not lines:
            return user_message

        # 构建上下文块
        session_info = ""
        if session_id:
            session_info = (
                f"\nSession ID: {session_id}\n"
                f"Note: 上方为近期对话摘要。如需更多上下文，可参考会话历史。\n"
            )

        context_block = (
            f"<conversation_history>"
            f"{session_info}\n"
            f"{''.join(lines)}\n"
            f"</conversation_history>\n\n"
            f"{user_message}"
        )

        logger.debug(
            "[ContextBuilder] built context: %d messages, %d chars, session=%s",
            len(lines), total_chars, session_id,
        )
        return context_block

    def build_recovery_prompt(
        self,
        session_id: str,
        user_message: str,
        jsonl_path: str = "",
        title: str = "",
    ) -> str:
        """构建 Session 恢复 prompt。

        当 Agent 连接断开（模型切换、超时、SDK 重启等）后，
        注入 <session_recovery> 标签指向完整历史文件，
        让 LLM 先读取历史再无缝继续工作。

        Args:
            session_id: 会话 ID
            user_message: 用户最新消息
            jsonl_path: JSONL 历史文件路径
            title: 会话标题

        Returns:
            包含恢复指引的 prompt
        """
        if not jsonl_path:
            jsonl_path = str(self._sessions_dir / f"{session_id}.jsonl")

        display_title = title or session_id
        recovery_block = (
            f"<session_recovery>\n"
            f"你正在接续一个已有的会话（因连接中断需要重新建立上下文）。\n"
            f"当前会话的完整历史记录在下方，请先阅读以恢复上下文，然后继续处理用户的最新请求。\n"
            f"<session id=\"{session_id}\" title=\"{_escape_attr(display_title)}\">\n"
            f"History path: {jsonl_path}\n"
            f"</session>\n"
            f"</session_recovery>"
        )

        logger.info(
            "[ContextBuilder] built recovery prompt: session=%s, path=%s",
            session_id, jsonl_path,
        )
        return f"{recovery_block}\n\n{user_message}"

    def build_cross_session_ref(
        self,
        current_session_id: str,
        referenced_sessions: list[dict],
    ) -> str:
        """构建跨会话引用块。

        当用户在消息中引用其他会话时（如 @session_id），
        生成 <referenced_sessions> 块让 Agent 知道可以读取哪些会话。

        Args:
            current_session_id: 当前会话 ID
            referenced_sessions: 被引用的会话列表，每项包含 id, title, updated_at

        Returns:
            跨会话引用 XML 块，无引用时返回空字符串
        """
        blocks: list[str] = []
        for s in referenced_sessions:
            sid = s.get("id", "")
            if sid == current_session_id:
                continue
            title = _escape_attr(s.get("title", sid))
            updated = s.get("updated_at", "")
            jsonl = self._sessions_dir / f"{sid}.jsonl"
            blocks.append(
                f'<session id="{sid}" title="{title}" updatedAt="{updated}">\n'
                f"History path: {jsonl}\n"
                f"</session>"
            )

        if not blocks:
            return ""

        return (
            "<referenced_sessions>\n"
            "用户在消息中引用了其他会话。不要假设这些会话的内容；"
            "需要上下文时，请先读取对应的 History path。\n"
            + "\n\n".join(blocks)
            + "\n</referenced_sessions>"
        )

    def read_partial_history(
        self,
        session_id: str,
        max_turns: int = 5,
    ) -> list[MessageEntry]:
        """读取部分历史（用于 recovery 场景的快速预览）。

        直接读 JSONL 文件，不依赖 SessionManager。
        """
        jsonl_path = self._sessions_dir / f"{session_id}.jsonl"
        if not jsonl_path.exists():
            return []

        entries: list[MessageEntry] = []
        try:
            lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
            for line in lines:
                if not line.strip():
                    continue
                data = json.loads(line)
                if "role" in data:
                    entries.append(MessageEntry(**data))
            # 返回最后 max_turns*2 条
            tail = max_turns * 2
            return entries[-tail:] if len(entries) > tail else entries
        except Exception as exc:
            logger.warning("[ContextBuilder] failed to read %s: %s", jsonl_path, exc)
            return []


def _escape_attr(value: str) -> str:
    """转义 XML 属性值中的特殊字符。"""
    return (
        value
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

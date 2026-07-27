"""直答旁路 —— 简单问答跳过 CrewAI 编排，单次 LLM 调用直接回复。

背景：完整的 Crew 编排（Agent 构建 + 工具注入 + 多轮推理）对"你好""解释一下
XX 概念"这类纯对话是巨大浪费，实测首 token 常超 30s。本模块提供：

1. ``is_simple_chat``   —— 保守的启发式意图分类：只有"确定不需要工具"的消息
   才走旁路；任何疑似任务型请求（文件/搜索/生成/定时…）都回退完整编排。
2. ``build_direct_answer_fn`` —— 构建与 AgentFn 同签名的直答函数：经
   model_router 选 general_chat 模型，单次 chat completion，无工具。

Runner 在旁路失败（LLM 异常）时自动回退完整编排，保证行为只会变快不会变差。
开关：``feature_flags.enable_direct_answer_bypass``（默认开启）。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from xiaopaw.session.models import MessageEntry

logger = logging.getLogger(__name__)

# 旁路只接受较短的消息：长消息大概率是任务描述/粘贴的材料。
_MAX_SIMPLE_CHARS = 300

# 命中任一关键词 → 疑似需要工具/编排，不走旁路（保守白名单思路：宁可漏放）。
_TASK_KEYWORDS = (
    # 文件与产出物
    "文件", "文档", "报告", "表格", "导出", "下载", "上传", "保存",
    "ppt", "pdf", "docx", "excel", "word", "markdown",
    # 联网与检索
    "搜索", "搜一下", "查一下", "检索", "联网", "网页", "浏览", "爬",
    "http://", "https://", "url", "链接",
    # 执行类
    "执行", "运行", "脚本", "命令", "部署", "安装", "sandbox", "沙箱",
    # 自动化
    "定时", "提醒", "日程", "每天", "每周", "cron",
    # 记忆与技能
    "记住", "记忆", "备忘", "技能", "skill",
    # 生成类（图片/代码工程通常要走工具或专用模型）
    "生成", "制作", "画一", "绘制", "写一份", "写个", "帮我做",
)

# 直答系统提示：明确边界，避免模型假装调用了工具。
_SYSTEM_PROMPT = (
    "你是「玄机」AI 工作助手。当前处于快速问答模式：直接、简洁地回答用户的"
    "问题，不要声称你已执行了搜索、文件操作等动作（此模式下没有工具可用）。"
    "如果问题需要联网检索、操作文件或执行任务才能可靠回答，请如实说明并建议"
    "用户补充明确的任务指令。用中文回答。"
)

_slash_re = re.compile(r"^\s*/")


def is_simple_chat(content: str) -> bool:
    """保守判定 *content* 是否为可直答的简单问答。

    返回 True 的条件（全部满足）：
    - 非空、非 slash 命令、长度 ≤ 300 字符
    - 不含任何任务型关键词 / URL

    分类器故意偏保守：误判为"复杂"只损失速度（走原编排路径），
    误判为"简单"则会丢失工具能力，因此关键词表宁可过宽。
    """
    text = (content or "").strip()
    if not text or len(text) > _MAX_SIMPLE_CHARS:
        return False
    if _slash_re.match(text):
        return False
    lowered = text.lower()
    return not any(kw in lowered for kw in _TASK_KEYWORDS)


def build_direct_answer_fn(max_history_turns: int = 10):
    """构建与 AgentFn 同签名的直答函数（供 Runner 作为旁路调用）。

    LLM 经 model_router 按 ``general_chat`` 路由选择（通常是低延迟的
    flash 档），单次调用、不带工具；历史仅取最近 *max_history_turns* 条。
    """

    async def direct_answer_fn(
        user_message: str,
        history: list[MessageEntry],
        session_id: str,
        routing_key: str = "",
        verbose: bool = False,
    ) -> tuple[str, list[str]]:
        from xiaopaw.llm.model_router import model_router

        llm = model_router.get_llm(task_type="general_chat")

        messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        for entry in history[-max_history_turns:]:
            role = entry.role if entry.role in ("user", "assistant") else "user"
            messages.append({"role": role, "content": entry.content})
        messages.append({"role": "user", "content": user_message})

        start = time.monotonic()
        # AliyunLLM.call 是同步（requests）实现，放线程池避免阻塞事件循环。
        reply = await asyncio.to_thread(llm.call, messages)
        logger.info(
            "direct-answer bypass: session=%s model=%s latency=%.2fs",
            session_id[:12], getattr(llm, "model", "?"),
            time.monotonic() - start,
        )
        return (reply or "").strip(), []

    return direct_answer_fn

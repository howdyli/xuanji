"""Async turn indexer for pgvector semantic search."""

from __future__ import annotations

import hashlib
import logging
import re
from functools import cache

logger = logging.getLogger(__name__)


# ================================================================
# Phase B2: 多因子重要性评分（纯本地计算，与 remote_memory._score_importance_v2 同逻辑）
# ================================================================

_KW_EXPLICIT = re.compile(r"记住|别忘了|remember|必须记住|please remember", re.IGNORECASE)
_KW_IDENTITY = re.compile(r"我是|我的名字|我喜欢|我不喜欢|叫我")
_KW_WORK = re.compile(r"项目|工作|任务|deadline|进度")
_KW_CHITCHAT = re.compile(r"^你好|^hi|^hello|^嗨|^谢谢|^thanks|^好的|^ok", re.IGNORECASE)
_STRONG_EMOTION = re.compile(r"[!！]{2,}|非常|超级|极其|特别|绝对|一定|千万")
_ENTITY_PERSON = re.compile(r"\b([A-Z][a-z]+)\b")
_ENTITY_ORG = re.compile(r"(公司|集团|学院|医院|大学|银行|机构|团队)")
_ENTITY_LOCATION = re.compile(r"(市|区|省|路|街|大厦|国家)")
_ENTITY_DATE = re.compile(r"\d{1,4}[年/-]\d{1,2}[月/-]\d{0,2}日?")


def _score_importance_v2(text: str) -> float:
    """多因子重要性评分（0.0 ~ 1.0），纯本地计算。

    因子与权重：
    - 关键词匹配（0.30）：5 档
    - 用户显式标记（0.30）
    - 实体密度（0.20）
    - 消息长度（0.10）
    - 情感强度（0.10）

    最终分数 clamp 到 [0.05, 0.95]。
    """
    try:
        if not text or not text.strip():
            return 0.05

        # 1. 关键词匹配（0.30）
        if _KW_EXPLICIT.search(text):
            kw_score = 0.9
        elif _KW_IDENTITY.search(text):
            kw_score = 0.7
        elif _KW_WORK.search(text):
            kw_score = 0.5
        elif _KW_CHITCHAT.search(text):
            kw_score = 0.1
        else:
            kw_score = 0.3

        # 2. 用户显式标记（0.30）
        explicit_score = 1.0 if _KW_EXPLICIT.search(text) else 0.3

        # 3. 实体密度（0.20）
        entity_count = 0
        if _ENTITY_PERSON.search(text):
            entity_count += 1
        if _ENTITY_ORG.search(text):
            entity_count += 1
        if _ENTITY_LOCATION.search(text):
            entity_count += 1
        if _ENTITY_DATE.search(text):
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
        emotion_score = 0.8 if (_STRONG_EMOTION.search(text) or "!" in text or "！" in text) else 0.3

        # 加权求和
        final = (
            0.30 * kw_score
            + 0.30 * explicit_score
            + 0.20 * entity_score
            + 0.10 * len_score
            + 0.10 * emotion_score
        )
        return max(0.05, min(0.95, final))

    except Exception:
        logger.debug("_score_importance_v2 failed, using default 0.4")
        return 0.4


@cache
def _get_llm_client():
    """Singleton OpenAI-compatible client for summarization."""
    try:
        from openai import OpenAI
        import os
        return OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("QWEN_API_KEY", ""),
            base_url=os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get("QWEN_BASE_URL", "https://api.deepseek.com/v1"),
        )
    except ImportError:
        logger.warning("openai package not installed, indexing disabled")
        return None


_embed_unavailable_warned = False


@cache
def _get_embedding_client():
    """Singleton client for text-embedding-v3（DashScope/Qwen 专用）。

    DeepSeek 没有 embeddings 端点，直接用 DeepSeek base_url 调
    text-embedding-v3 会 404，因此 embedding 必须走 DashScope 兼容端点；
    未配置 QWEN/DASHSCOPE Key 时返回 None，由调用方跳过向量索引。
    """
    try:
        from openai import OpenAI
        import os
        api_key = os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            return None
        return OpenAI(
            api_key=api_key,
            base_url=os.environ.get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
    except ImportError:
        return None


def _content_hash(session_id: str, turn_ts: int) -> str:
    raw = f"{session_id}:{turn_ts}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _classify_fragment_type(messages: list[dict]) -> str:
    """根据消息内容简单分类记忆类型。"""
    text = " ".join(m.get("content", "") for m in messages if m.get("role") == "user")
    plan_keywords = ["计划", "目标", "打算", "准备", "下一步", "规划", "plan", "goal"]
    pref_keywords = ["偏好", "喜欢", "不喜欢", "讨厌", "习惯", "prefer", "like", "dislike"]
    if any(kw in text for kw in plan_keywords):
        return "plan"
    if any(kw in text for kw in pref_keywords):
        return "preference"
    return "info"  # 默认


async def async_index_turn(
    session_id: str,
    routing_key: str,
    user_message: str,
    assistant_reply: str,
    turn_ts: int,
    db_dsn: str,
    messages: list[dict] | None = None,
    content_id: str | None = None,
    remote_synced: bool = True,
    fragment_type: str | None = None,
) -> None:
    """Extract summary, embed, and upsert into pgvector. Fire-and-forget safe.

    content_id: 显式主键（memory_sync 全量同步用远程片段 id，避免
        created_ts 缺失时 hash 碰撞）；None 时按 session_id+turn_ts 计算。
    remote_synced: 双写一致性标记；远程写入失败时传 False，
        由 memory_sync.full_sync 后续补偿推送。
    fragment_type: P3 差异化 TTL —— 调用方显式传入时优先使用，
        否则根据消息内容自动分类（info / plan / preference）。
    """
    if not db_dsn:
        return

    client = _get_llm_client()
    if client is None:
        return

    embed_client = _get_embedding_client()
    if embed_client is None:
        global _embed_unavailable_warned
        if not _embed_unavailable_warned:
            _embed_unavailable_warned = True
            logger.warning(
                "no embedding-capable API key (QWEN_API_KEY/DASHSCOPE_API_KEY); "
                "L21 pgvector indexing skipped (remote memory is unaffected)"
            )
        return

    try:
        content_id = content_id or _content_hash(session_id, turn_ts)

        # 先查重：已存在则直接返回，避免重复消耗 LLM 总结/embedding 调用
        import psycopg2
        conn = psycopg2.connect(db_dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM memories WHERE id = %s", (content_id,))
                if cur.fetchone() is not None:
                    return
        finally:
            conn.close()

        # ✅ P2-1: 优先使用 ModelRouter 选择 memory_indexing 任务模型
        try:
            from xiaopaw.llm.model_router import model_router as _indexer_router
            if _indexer_router._models:
                # 获取 LLM 实例并提取配置信息
                llm_instance = _indexer_router.get_llm(task_type="memory_indexing")
                model_name = getattr(llm_instance, 'model', 'deepseek-chat')
            else:
                model_name = "deepseek-chat"
        except Exception:
            model_name = "deepseek-chat"

        summary_resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "用一句中文总结以下对话的核心内容，提取关键实体和主题标签。"},
                {"role": "user", "content": f"用户：{user_message}\n助手：{assistant_reply[:500]}"},
            ],
            max_tokens=200,
        )
        summary = summary_resp.choices[0].message.content or ""

        embed_resp = embed_client.embeddings.create(
            model="text-embedding-v3",
            input=[summary, user_message],
            dimensions=1024,
        )
        summary_vec = embed_resp.data[0].embedding
        message_vec = embed_resp.data[1].embedding

        search_text = f"{user_message} {summary}"

        # Phase A3: 根据消息内容分类 fragment_type（调用方显式传入时优先）
        if fragment_type:
            final_fragment_type = fragment_type
        elif messages:
            final_fragment_type = _classify_fragment_type(messages)
        else:
            # 回退：用 user_message 单条分类
            final_fragment_type = _classify_fragment_type([{"role": "user", "content": user_message}])

        # Phase B2: 使用 v2 多因子评分计算 importance_score
        importance_score = _score_importance_v2(summary or user_message)

        import psycopg2
        conn = psycopg2.connect(db_dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO memories
                       (id, session_id, routing_key, user_message, assistant_reply,
                        summary, tags, turn_ts, summary_vec, message_vec, search_text,
                        fragment_type, importance_score, remote_synced)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO NOTHING""",
                    (
                        content_id, session_id, routing_key,
                        user_message, assistant_reply[:2000],
                        summary, [], turn_ts,
                        str(summary_vec), str(message_vec), search_text,
                        final_fragment_type, importance_score, remote_synced,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        logger.info("indexed turn %s for session %s", content_id, session_id)

    except Exception:
        logger.exception("index_turn failed for session %s", session_id)

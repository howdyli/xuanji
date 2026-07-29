"""
scripts/search.py — 混合检索执行脚本

供 search_memory Skill 的 Sub-Crew 调用。
封装 pgvector 连接和查询，模型只需传参数，不需要关心数据库细节。

用法：
  python scripts/search.py --query "航班查询" --mode hybrid --limit 5
  python scripts/search.py --query "PDF转换" --tags "文件处理" --days 7
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import psycopg2
import psycopg2.extras
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────────────────────

DB_DSN = os.getenv(
    "MEMORY_DB_DSN",
    "postgresql://xiaopaw:xiaopaw123@localhost:5432/xiaopaw_memory",
)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("QWEN_API_KEY", "")
EMBED_MODEL  = "text-embedding-v3"
EMBED_DIM    = 1024

_embed_client = None
_EMBED_WARNED = False

def get_embed_client():
    """获取嵌入客户端（惰性初始化），API Key 为空时返回 None。"""
    global _embed_client, _EMBED_WARNED
    if _embed_client is None:
        if not DEEPSEEK_API_KEY:
            if not _EMBED_WARNED:
                print("[WARN] 未配置嵌入 API Key（DEEPSEEK_API_KEY / QWEN_API_KEY），向量搜索降级为纯文本检索",
                      file=sys.stderr)
                _EMBED_WARNED = True
            return None
        _embed_client = OpenAI(
            api_key  = DEEPSEEK_API_KEY,
            base_url = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("QWEN_BASE_URL", "https://api.deepseek.com/v1"),
        )
    return _embed_client


# ─────────────────────────────────────────────────────────────────────────────
# 向量化查询词
# ─────────────────────────────────────────────────────────────────────────────

def embed_query(query: str) -> list[float]:
    client = get_embed_client()
    if client is None:
        return []  # API Key 未配置，返回空向量，后续查询将跳过向量部分
    resp = client.embeddings.create(
        model      = EMBED_MODEL,
        input      = [query],
        dimensions = EMBED_DIM,
    )
    return resp.data[0].embedding


# ─────────────────────────────────────────────────────────────────────────────
# 搜索函数
# ─────────────────────────────────────────────────────────────────────────────

def search(
    query:       str,
    tags:        list[str] | None = None,
    days:        int | None       = None,
    routing_key: str | None       = None,
    limit:       int              = 5,
    mode:        str              = "hybrid",   # hybrid / vector / fulltext
) -> list[dict]:
    """
    💡 核心点：混合检索 = 向量语义 + BM25全文 + 标量过滤，一条 SQL 搞定
    向量得分权重 0.7，全文得分权重 0.3
    """
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = True

    # 构建标量过滤条件
    where_clauses = []
    params: dict = {}

    if tags:
        where_clauses.append("tags && %(tags)s")          # 💡 && = 数组有交集
        params["tags"] = tags

    if days:
        # 💡 核心点：INTERVAL 内部不支持 psycopg2 参数替换，用 make_interval() 代替
        where_clauses.append("created_at > NOW() - make_interval(days => %(days)s)")
        params["days"] = days

    if routing_key:
        where_clauses.append("routing_key = %(routing_key)s")
        params["routing_key"] = routing_key

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    query_vec = embed_query(query)
    has_vector = bool(query_vec)  # API Key 未配置时返回空列表

    results = []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

        if mode == "vector" and not has_vector:
            # ── 向量模式但无 API Key → 降级为全文搜索 ────────────────────────
            print("[WARN] 向量搜索不可用（无 API Key），降级为全文搜索", file=sys.stderr)
            mode = "fulltext"

        if mode == "vector":
            # ── 纯向量搜索 ────────────────────────────────────────────────────
            params["query_vec"] = str(query_vec)
            params["limit"]     = limit
            cur.execute(
                f"""
                SELECT
                    id, summary, user_message, assistant_reply, tags,
                    created_at, turn_ts,
                    1 - (summary_vec <=> %(query_vec)s::vector) AS score
                FROM memories
                {where_sql}
                ORDER BY summary_vec <=> %(query_vec)s::vector
                LIMIT %(limit)s
                """,
                params,
            )
            results = [dict(r) for r in cur.fetchall()]

        elif mode == "fulltext":
            # ── 纯全文搜索（BM25 近似）────────────────────────────────────────
            params["tsquery"] = query
            params["limit"]   = limit
            cur.execute(
                f"""
                SELECT
                    id, summary, user_message, assistant_reply, tags,
                    created_at, turn_ts,
                    ts_rank(search_tsv, plainto_tsquery('simple', %(tsquery)s)) AS score
                FROM memories
                {where_sql}
                {"AND" if where_clauses else "WHERE"} search_tsv @@ plainto_tsquery('simple', %(tsquery)s)
                ORDER BY score DESC
                LIMIT %(limit)s
                """,
                params,
            )
            results = [dict(r) for r in cur.fetchall()]

        else:
            # ── 混合搜索（推荐）：向量 × 0.7 + 全文 × 0.3 ────────────────────
            if not has_vector:
                # 无 API Key 时混合搜索降级为纯全文搜索
                print("[WARN] 混合搜索不可用（无 API Key），降级为全文搜索", file=sys.stderr)
                params["tsquery"] = query
                params["limit"]   = limit
                cur.execute(
                    f"""
                    SELECT
                        id, summary, user_message, assistant_reply, tags,
                        created_at, turn_ts,
                        ts_rank(search_tsv, plainto_tsquery('simple', %(tsquery)s)) AS score
                    FROM memories
                    {where_sql}
                    {"AND" if where_clauses else "WHERE"} search_tsv @@ plainto_tsquery('simple', %(tsquery)s)
                    ORDER BY score DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
            else:
                params["query_vec"] = str(query_vec)
                params["tsquery"]   = query
                params["limit"]     = limit
                cur.execute(
                    f"""
                    SELECT
                        id, summary, user_message, assistant_reply, tags,
                        created_at, turn_ts,
                        (
                            0.7 * (1 - (summary_vec <=> %(query_vec)s::vector))
                            + 0.3 * ts_rank(search_tsv, plainto_tsquery('simple', %(tsquery)s))
                        ) AS score
                    FROM memories
                    {where_sql}
                    -- 💡 核心点：对全表同时计算向量得分和全文得分，加权求和后排序
                    -- 向量得分兜底语义相关，全文得分加权精确匹配，两者互补
                    ORDER BY score DESC
                    LIMIT %(limit)s
                    """,
                    params,
                )
            results = [dict(r) for r in cur.fetchall()]

    conn.close()

    # 序列化（datetime → str，score 保留4位小数）
    for r in results:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
        if r.get("score") is not None:   # 💡 显式判断 None，避免 score=0.0 被漏掉
            r["score"] = round(float(r["score"]), 4)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="XiaoPaw 记忆混合检索")
    parser.add_argument("--query",       required=True,  help="搜索意图（自然语言）")
    parser.add_argument("--tags",        default=None,   help="标签过滤，逗号分隔（如 工作,文件处理）")
    parser.add_argument("--days",        type=int, default=None, help="时间范围，最近N天")
    parser.add_argument("--routing_key", default=None,   help="限定用户")
    parser.add_argument("--limit",       type=int, default=5, help="返回条数")
    parser.add_argument("--mode",        default="hybrid", choices=["hybrid", "vector", "fulltext"])
    args = parser.parse_args()

    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None

    try:
        results = search(
            query       = args.query,
            tags        = tags,
            days        = args.days,
            routing_key = args.routing_key,
            limit       = args.limit,
            mode        = args.mode,
        )
        print(json.dumps(results, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()


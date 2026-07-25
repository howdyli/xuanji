"""KnowledgeSearchTool: agent-invoked hybrid retrieval over the knowledge base.

Mirrors ``BaiduSearchTool``'s shape. Tenant context (``routing_key`` / optional
``org_id``) and the DB DSN are injected at construction by the crew — never
supplied by the LLM — so retrieval cannot escape the caller's tenant.

P0 scopes the agent tool to the caller's personal libraries (owner_key =
routing_key). Org-library retrieval from within a chat arrives with the P1
session-binding work that threads org context into the crew.
"""

from __future__ import annotations

import logging

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class KnowledgeSearchInput(BaseModel):
    query: str = Field(description="要在知识库中检索的问题或关键词")
    kb_id: str | None = Field(default=None, description="限定某个知识库 ID，留空则检索全部可见知识库")
    top_k: int = Field(default=6, ge=1, le=20, description="返回片段数量，默认 6")


class KnowledgeSearchTool(BaseTool):
    name: str = "search_knowledge_base"
    description: str = (
        "在用户的知识库（已上传的文档）中检索相关内容。当问题可能依赖用户上传的资料、"
        "内部文档或专业知识时使用。返回带编号的片段；在回答中引用事实时，请用对应的 "
        "[编号] 标注来源。参数：query（必填）、kb_id（可选，限定某库）、top_k（默认6）。"
    )
    args_schema: type = KnowledgeSearchInput

    # Injected at construction (not by the LLM):
    routing_key: str = ""
    db_dsn: str = ""
    org_id: int | None = None
    default_top_k: int = 6
    # Session-bound base allowlist: non-empty restricts retrieval to these
    # bases (LLM-supplied kb_id outside the list is ignored, not an error).
    allowed_kb_ids: list[str] | None = None

    def _run(self, query: str, kb_id: str | None = None, top_k: int | None = None, **_) -> str:
        if not self.db_dsn:
            return "知识库未配置（缺少数据库连接）。"
        if not query or not query.strip():
            return "检索关键词不能为空。"

        from xiaopaw.knowledge.retriever import format_for_agent, retrieve
        from xiaopaw.knowledge.store import KnowledgeStore

        # Resolve the effective scope: session bindings (allowlist) win over
        # the LLM-supplied kb_id; an out-of-list kb_id falls back to the
        # whole allowlist with a notice instead of failing the call.
        notice = ""
        effective_kb_id = kb_id
        effective_kb_ids: list[str] | None = None
        if self.allowed_kb_ids:
            if kb_id and kb_id in self.allowed_kb_ids:
                effective_kb_ids = [kb_id]
            else:
                if kb_id:
                    notice = (
                        f"（提示：kb_id={kb_id} 不在当前会话绑定的知识库范围内，"
                        "已改为在绑定的知识库内检索。）\n"
                    )
                effective_kb_ids = list(self.allowed_kb_ids)
            effective_kb_id = None

        try:
            store = KnowledgeStore(self.db_dsn)
            chunks = retrieve(
                store,
                query=query.strip(),
                owner_key=self.routing_key,
                org_id=self.org_id,
                kb_id=effective_kb_id,
                kb_ids=effective_kb_ids,
                top_k=top_k or self.default_top_k,
            )
        except Exception as exc:
            logger.exception("knowledge search failed")
            return f"知识库检索失败：{exc}"

        return notice + format_for_agent(chunks)

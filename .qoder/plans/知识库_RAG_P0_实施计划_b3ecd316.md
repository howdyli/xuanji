# 知识库 RAG P0 实施计划

基于已评审并提交的设计 spec：[2026-07-08-knowledge-base-rag-design.md](file:///Users/howdy/work-source/xiaopaw-v2/docs/superpowers/specs/2026-07-08-knowledge-base-rag-design.md)。本计划仅覆盖 **P0（首版可用）**：文件上传 → 异步摄取 → 工具式混合检索 → 引用溯源 → 知识库管理 UI。会话/专家绑定的自动前置检索、URL/飞书导入分别留待 P1/P2。

## 数据层（Schema）
- 在 `schema.sql` 追加 4 张幂等表：`knowledge_bases`、`knowledge_documents`、`knowledge_chunks`（`embedding vector(1024)` + HNSW cosine + `search_tsv` GIN）、`session_knowledge_bases`（P0 仅建表，绑定逻辑 P1 用）。
- 索引与租户过滤字段（`owner_key`/`org_id`/`kb_id`）齐备，维度 1024 与 `memories` 对齐。
- 验收：对空库执行 schema 幂等无报错；`\d knowledge_chunks` 显示 HNSW 与 GIN 索引。

## 摄取管线（后端，进程内 asyncio）
- 新增 `xiaopaw/knowledge/` 包：`adapters.py`（`SourceAdapter` 协议 + `FileAdapter`：pdf=pypdf、docx=python-docx、md/txt 直读，产出 `(text, meta)` 且保留 `locator`）、`chunker.py`（递归切分 ~500 token/块、重叠 ~80，复用 `memory/token_counter.py`）、`embedder.py`（复用 `indexer.py` 的 OpenAI 兼容客户端，`text-embedding-v3` dim=1024，分批 16）、`ingest.py`（`ingest_document(doc_id)`：processing→抽取→切块→批量嵌入→upsert chunks→ready；异常→failed+error_msg）。
- 文件落盘到 workspace 下 kb 存储目录；上传接口 `asyncio.create_task` 触发摄取，立即 202。
- 启动兜底：扫描 `status=processing` 且 `updated_at` 超时（>10min）→ 重置 pending 重新入队（挂到 app 启动钩子）。
- 依赖：在 `pyproject.toml` 增补 `pypdf`、`python-docx`。
- 验收：单测覆盖 Chunker 边界/重叠、FileAdapter 三格式抽取（小样本 fixture）、ingest 失败路径置 failed。

## 检索（后端）
- 新增 `xiaopaw/knowledge/retriever.py`：混合检索 = 向量 cosine Top-N + tsvector 全文 Top-N，用 RRF 融合取 top_k；SQL 强制带租户过滤（`owner_key`/`org_id`），入参不接受 LLM 指定的租户字段。
- 新增 `xiaopaw/tools/knowledge_search_tool.py::KnowledgeSearchTool`（`crewai.tools.BaseTool`，与 `BaiduSearchTool` 同构），构造时注入当前 `routing_key`/`org_id`；入参 `query/kb_id?/top_k=6`；返回带 `[n]` 编号片段 + `document_id/chunk_index/文档名/locator`。
- 装配：在 `xiaopaw/agents/main_crew.py` 的 `tools=[skill_tool, IntermediateTool()]` 追加 `KnowledgeSearchTool` 实例；`xiaopaw/tools/__init__.py` 导出。
- 验收：单测覆盖 RRF 融合排序、租户过滤 SQL；集成测试检索命中。

## 引用溯源（后端 → 前端贯通）
- 工具返回的片段块编号化并附来源表；确保 `citations` 结构可从工具结果解析并随 SSE 回复下发（`{n, document_id, chunk_index, title, locator, snippet}`）。
- P0 以「工具式检索 + 回复末尾来源清单 + 可点击角标」为准（自动前置注入属 P1，不在本期）。
- 验收：集成测试断言回复负载含 `citations` 且映射到真实 chunk。

## API（后端）
- 新增 `xiaopaw/frontend/routes/knowledge.py` + `register_knowledge_routes(app)`，注册进 `routes/__init__.py`，全部 `check_auth`：
  - `POST/GET /bases`、`DELETE /bases/{kb_id}`
  - `POST /bases/{kb_id}/documents`（multipart 上传→202）、`GET /bases/{kb_id}/documents`（含 status）
  - `GET /documents/{doc_id}`（详情+分页 chunks）、`DELETE /documents/{doc_id}`
  - `POST /search`（调试检索）
- 权限：personal 按 routing_key、org 写操作限管理员；复用 `routes/helpers.py` 解析。
- 验收：集成测试走「建库→上传→轮询 ready→search 命中→删除级联」全链路；跨租户访问返回 401/403。

## 前端（React）
- 侧边栏新增「知识库」入口（天蓝规范，与「素材库」区分）：库列表（个人/组织分组）+ 建库；进入库→文档列表 + 状态徽标（待处理/处理中/就绪/失败可重试）+ 上传（拖拽/选择）；文档详情分块预览。
- 复用现有 `apiFetch` 客户端；轮询文档 status 直至 ready/failed。
- 消息内 `[n]` 引用角标组件：点击弹层展示 citation 的 snippet 与来源，可跳转文档详情。
- 验收：vitest 覆盖库列表/上传状态流转与角标渲染；`tsc` 通过。

## 测试与验证
- 后端：`pytest` 单元（Chunker/Adapter/RRF/租户 SQL）+ 集成（沿用 `test_expert_injection` 的 aiohttp TestClient + CaptureSender 模式：上传→ready→search→citations→权限隔离）。
- 前端：`vitest` + `tsc`。
- 端到端：重启后端加载新路由与工具，Playwright 视觉验证建库/上传/就绪/检索引用（参照既往 e2e 流程）。

## 假设
- 复用现有 pgvector 实例与 DashScope embedding 凭据；无需新增外部依赖服务。
- P0 文档更新采用「删文档重传」，不做增量重建。
- `session_knowledge_bases` 表本期只建不接线（自动前置检索属 P1）。

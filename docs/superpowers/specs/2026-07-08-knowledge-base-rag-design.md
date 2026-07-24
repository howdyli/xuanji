# 知识库 RAG（文档检索增强）设计方案

- 状态：Draft（待评审）
- 日期：2026-07-08
- 作者：玄机团队
- 关联：对标 Claude Projects / ChatGPT Team / Glean 的知识库能力；补齐产品缺口分析中的 P0 项

## 1. 背景与目标

现有系统已具备 pgvector 语义记忆（`memories` 表）、DashScope `text-embedding-v3`（1024 维）
embedding 客户端、CrewAI 工具编排（如 `BaiduSearchTool`）、多租户 `routing_key` + `org_id`
隔离、飞书接入、后台任务基建。但缺少「用户可上传/导入文档 → 检索增强问答 → 带引用溯源」
的知识库能力。

本方案实现一个**个人 + 组织双层级**的知识库：用户上传文件（后续支持 URL / 飞书文档），
系统异步解析、切块、向量化并落库；Agent 在对话中既能**按需调用检索工具**，也能在会话/专家
**绑定知识库时自动前置检索**；回答带**可点击的内联引用角标**溯源到原文片段。

### 决策快照（评审确认）

| 编号 | 决策点 | 结论 |
|---|---|---|
| Q1 | 归属/可见性模型 | **个人 + 组织双层级**（personal 按 routing_key，org 按 org_id） |
| Q2 | 文档来源 | **文件 + URL + 飞书**（统一 Source Adapter 接口，分期接入） |
| Q3 | 检索接入方式 | **混合式**：默认工具式按需查；会话/专家绑定知识库时自动前置检索 |
| Q4 | 引用溯源 | **强制内联引用**：`[n]` 角标 + 来源清单，前端可点击查看原文片段 |
| Q5 | 摄取时机 | **异步后台处理**，状态可见（pending/processing/ready/failed） |
| A | 向量存储 | **A1：复用 pgvector，新建 `knowledge_*` 表**，沿用 HNSW + tsvector 混合检索 |
| B | 摄取 worker | **B1：进程内 asyncio 后台任务** + DB 状态字段 + 超时重置兜底 |

### 命名边界

- **知识库（Knowledge Base）**：本方案新增的 RAG 文档库。
- **素材库（Library）**：现有 `routes/library.py`，只读扫描 `sessions/*/outputs/` 的产物文件浏览器，与本方案无关，保持不变。

## 2. 数据模型

追加进 `schema.sql`（幂等 `CREATE TABLE IF NOT EXISTS`）。向量维度 1024，与 `memories` 一致。

```sql
-- 知识库容器
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id          TEXT PRIMARY KEY,               -- kb-<uuid>
    name        TEXT NOT NULL,
    scope       TEXT NOT NULL CHECK (scope IN ('personal','org')),
    owner_key   TEXT NOT NULL DEFAULT '',       -- routing_key（personal 库归属）
    org_id      BIGINT,                          -- org 库归属
    description TEXT NOT NULL DEFAULT '',
    created_by  TEXT NOT NULL DEFAULT '',        -- username
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kb_owner ON knowledge_bases (scope, owner_key);
CREATE INDEX IF NOT EXISTS idx_kb_org   ON knowledge_bases (scope, org_id);

-- 单篇文档
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id          TEXT PRIMARY KEY,               -- doc-<uuid>
    kb_id       TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('file','url','feishu')),
    source_uri  TEXT NOT NULL DEFAULT '',        -- 原始文件路径/URL/飞书 token
    mime        TEXT NOT NULL DEFAULT '',
    byte_size   BIGINT NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','processing','ready','failed')),
    error_msg   TEXT NOT NULL DEFAULT '',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kdoc_kb     ON knowledge_documents (kb_id);
CREATE INDEX IF NOT EXISTS idx_kdoc_status ON knowledge_documents (status);

-- 切块 + 向量（检索单元）
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id          TEXT PRIMARY KEY,               -- chk-<uuid>
    doc_id      TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    kb_id       TEXT NOT NULL,                   -- 冗余，便于按库过滤检索
    chunk_index INTEGER NOT NULL,
    content     TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    locator     TEXT NOT NULL DEFAULT '',        -- 定位信息：page=3 / heading=... （溯源用）
    embedding   vector(1024),
    search_text TEXT NOT NULL DEFAULT '',
    search_tsv  TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', search_text)) STORED,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kchunk_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_kchunk_tsv ON knowledge_chunks USING gin (search_tsv);
CREATE INDEX IF NOT EXISTS idx_kchunk_kb  ON knowledge_chunks (kb_id);
CREATE INDEX IF NOT EXISTS idx_kchunk_doc ON knowledge_chunks (doc_id);

-- 会话 ↔ 知识库绑定（自动前置检索开关）
CREATE TABLE IF NOT EXISTS session_knowledge_bases (
    session_id TEXT NOT NULL,
    kb_id      TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, kb_id)
);
CREATE INDEX IF NOT EXISTS idx_skb_session ON session_knowledge_bases (session_id);
```

### 权限隔离规则

- `personal` 库：仅 `owner_key = 当前 routing_key` 可见/可写。
- `org` 库：`org_id = 当前 org_id` 的成员可见；写入（建库/传文档/删除）默认限管理员，读取（检索）全员可用。
- 所有检索 SQL **强制**带租户过滤条件（禁止跨租户），复用 `routes/helpers.py` 的 routing_key / org_id 解析。

## 3. 摄取管线（异步，进程内 asyncio）

```
上传/导入
  → 写 knowledge_documents(status=pending)（若为文件，先落盘到 workspace 下的 kb 存储目录）
  → API 立即返回 202 + document_id
  → 提交后台任务 asyncio.create_task(ingest_document(doc_id))

ingest_document(doc_id):
  status=processing
  → SourceAdapter.extract(source) -> (text, meta)
  → Chunker.split(text, meta) -> [chunk...]        # ~500 token/块，重叠 ~80，按标题/段落边界优先
  → embed_batch([chunk.content ...])               # text-embedding-v3, dim=1024，复用 indexer 的客户端；分批（如每批 16）
  → 批量 upsert knowledge_chunks
  → status=ready, chunk_count=N, updated_at=now
  异常 → status=failed, error_msg=<截断的异常信息>

启动兜底：扫描 status=processing 且 updated_at 超时（如 >10min）的文档 → 重置为 pending 并重新入队。
```

### Source Adapter 接口

```python
class SourceAdapter(Protocol):
    def extract(self, source: DocumentSource) -> tuple[str, dict]:
        """返回 (纯文本, 元数据{title?, pages?, ...})；失败抛异常。"""
```

- **FileAdapter（P0）**：`.pdf`→pypdf、`.docx`→python-docx、`.md`/`.txt`→直读。逐页/逐段保留 `locator`。
- **UrlAdapter（P1）**：复用 `fetch` MCP 抓取 → HTML 正文提取（去导航/脚注）。
- **FeishuAdapter（P2）**：复用现有飞书 client，调用云文档/知识库 API 拉取文档富文本 → 纯文本。

### Chunker

- 默认按「标题层级 → 段落 → 句子」递归切分，目标 ~500 token/块、重叠 ~80 token。
- 复用 `xiaopaw/memory/token_counter.py` 计 token。
- 每块记录 `locator`（页码 / 标题路径），供引用定位。

## 4. 检索（混合式）

### 4.1 工具式（Agent 按需调用）

新增 `xiaopaw/tools/knowledge_search_tool.py::KnowledgeSearchTool`，`crewai.tools.BaseTool` 子类，
与 `BaiduSearchTool` 同构，挂到 `main_crew.py` 的 `tools=[skill_tool, IntermediateTool(), ...]`。

- 入参：`query: str`、`kb_id: str | None`（None=当前会话可见的全部库）、`top_k: int=6`。
- 逻辑：**混合检索**——向量 cosine 相似 Top-N 与 tsvector 全文 Top-N 各召回，用 RRF（Reciprocal Rank Fusion）融合排序取 top_k。
- 租户过滤：工具通过依赖注入拿到当前 `routing_key` / `org_id`（构造时绑定，不由 LLM 传入），SQL 强制过滤。
- 返回给 LLM 的文本：带编号的片段列表，每段附 `document_id / chunk_index / 文档名 / locator`。

### 4.2 自动前置检索（会话/专家绑定时）

- 在 `runner._handle` 中：若当前 session 存在 `session_knowledge_bases` 绑定，则对本轮用户 query 先做同样的混合检索，取 top-k 片段。
- 注入方式**复用专家注入的解耦模式**：把「带编号的检索片段块」作为带外上下文拼进 `agent_input`，**不写入** `inbound.content`、不污染会话历史与标题。
  ```
  agent_input = f"{retrieved_block}\n\n{expert_prompt_block}\n\n---\n\n{inbound.content}"
  ```
- 检索片段块与 citations 元数据一起向下传递，供最终回复组装引用。

## 5. 引用溯源

- 注入的检索片段块中，每段以 `[1] [2] …` 编号，并附「来源表：[n] 文档名 · locator」。
- system 提示追加约束：引用事实性内容时须使用对应编号 `[n]`。
- 回复通过 SSE 附带结构化 `citations`：
  ```json
  { "citations": [
      {"n": 1, "document_id": "doc-...", "chunk_index": 3,
       "title": "年报2025.pdf", "locator": "page=12", "snippet": "..."}
  ]}
  ```
- 前端把回答中的 `[n]` 渲染为可点击角标 → 点击弹出该 chunk 原文片段（并可跳转到文档详情定位到 chunk_index）。

## 6. API（新增 `xiaopaw/frontend/routes/knowledge.py`）

统一前缀 `/api/frontend/knowledge`，`register_knowledge_routes(app)` 注册到 `routes/__init__.py`。所有接口 `check_auth`。

| Method | Path | 说明 |
|---|---|---|
| POST | `/bases` | 建库（name/scope/description） |
| GET  | `/bases` | 列出当前用户可见库（个人 + 所属 org） |
| DELETE | `/bases/{kb_id}` | 删库（级联删文档/块，权限校验） |
| POST | `/bases/{kb_id}/documents` | 上传文件（multipart）或提交 url/feishu 引用 → 202 |
| GET  | `/bases/{kb_id}/documents` | 列文档（含 status/chunk_count/error_msg） |
| GET  | `/documents/{doc_id}` | 文档详情 + 分页 chunks（供引用查看原文） |
| DELETE | `/documents/{doc_id}` | 删文档（级联删 chunks） |
| POST | `/search` | 调试用检索（query/kb_id/top_k），返回融合结果 |
| PUT  | `/session/{session_id}/bases` | 设置会话绑定的知识库集合（绑定/解绑） |

## 7. 前端

- **侧边栏**新增「知识库」入口（沿用天蓝视觉规范）：
  - 库列表（个人/组织分组）→ 建库按钮。
  - 进入库 → 文档列表，状态徽标：`待处理 / 处理中 / 就绪 / 失败(可重试)`；上传按钮（拖拽/选择文件），后续加 URL/飞书导入入口。
  - 文档详情：分块预览。
- **会话内**：在统一输入框区域（与专家芯片同区）加「📚 知识库」选择器；绑定后显示知识库芯片、可解绑。绑定状态**按会话独立**（与专家一致的模型）。
- **消息内引用角标**组件：`[n]` 可点击 → 悬浮/弹层展示 citation 的 snippet 与来源，链接到文档详情。

## 8. 测试策略

- **单元**：Chunker 切分边界与重叠；RRF 融合排序；FileAdapter 各格式文本抽取（小样本 fixture）；租户过滤 SQL 生成。
- **集成**（沿用 `test_expert_injection` 的 aiohttp TestClient + CaptureSender 模式）：
  - 上传 → 轮询 status=ready → `/search` 命中。
  - 绑定知识库后自动前置检索：`agent_input` 含检索片段，而 `inbound.content` / 会话历史 / 标题**不含**检索文本（不污染）。
  - citations 结构随回复下发。
- **失败路径**：摄取异常 → status=failed + error_msg；启动扫描 processing 超时 → 重置 pending。
- **权限**：跨租户检索/访问被拒（personal 与 org 隔离）。

## 9. 分期落地

- **P0（首版可用）**：schema + `FileAdapter` + Chunker + 异步摄取 + `KnowledgeSearchTool`（工具式混合检索）+ citations + 知识库管理 UI（建库/传文件/列表/状态/删除）。
- **P1**：会话/专家绑定 + 自动前置检索；`UrlAdapter`；会话内知识库选择器与引用角标交互打磨。
- **P2**：`FeishuAdapter`；文档更新的增量重建（删旧 chunk 重嵌）；检索调参（权重/top_k）面板。

## 10. 风险与权衡

- **embedding 成本**：批量嵌入 + 仅在摄取时嵌入一次；检索时只嵌入 query。大文档分批，避免单次超限。
- **进程内 worker 崩溃**：靠 DB 状态 + 启动超时重置兜底；不引入外部队列（YAGNI），量级增大时可平滑迁到 cron/独立 worker。
- **切块质量**影响召回：首版用通用递归切分，P2 再按来源类型优化。
- **检索污染历史**：严格复用专家注入的带外解耦，杜绝检索文本进入用户可见文本/标题。
- **多租户越权**：租户过滤在服务端强制、工具入参不接受由 LLM 指定的 owner/org，防注入绕过。

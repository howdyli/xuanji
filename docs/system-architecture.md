# 玄机（XiaoPaw）系统架构设计文档

> 版本：v3.0 | 更新日期：2026-07-08

---

## 1. 系统概述

玄机（XiaoPaw）是一个**多渠道 AI 工作助手平台**，基于主从双层 Agent 架构，集成飞书即时通讯与 Web 前端双渠道。系统通过 Hook 框架实现零侵入安全加固，支持多模型智能路由、技能市场、三层记忆体系和知识库 RAG 检索。

### 1.1 核心能力

| 能力域 | 说明 |
|--------|------|
| 多渠道接入 | 飞书机器人（Webhook）+ Web 前端（REST API + SSE 流式） |
| 主从 Agent | Main Crew（编排推理）+ Sub-Crew（沙箱技能执行） |
| 技能体系 | 13 个内置技能 + 用户自定义 + 社区市场（发布/审核/安装） |
| 三层记忆 | Bootstrap（角色注入）+ 文件系统（workspace）+ pgvector（向量检索） |
| 知识库 RAG | 文档上传 → 分块 → 嵌入 → 混合检索（向量 + 全文） |
| 安全加固 | 5+2 Hook 事件体系（sandbox_guard / permission_gate / cost_guard / loop_detector） |
| 多模型路由 | 按任务类型/复杂度/成本自动选择最优 LLM，内置故障转移 |
| 多租户 RBAC | 个人/组织/团队三维隔离 + 细粒度角色权限 |

---

## 2. 技术栈

### 2.1 后端

| 组件 | 技术选型 | 版本 |
|------|----------|------|
| 运行时 | Python | ≥ 3.11 |
| Agent 框架 | CrewAI | ≥ 1.9.3 |
| HTTP 框架 | aiohttp | ≥ 3.9 |
| 数据验证 | Pydantic | ≥ 2.0 |
| 向量数据库 | PostgreSQL + pgvector | vector(1024) |
| 认证存储 | SQLite（auth.db） | WAL 模式 |
| 配置管理 | PyYAML + config.yaml | — |
| 可观测性 | Langfuse ≥ 4.0 + Prometheus | — |
| 沙箱 | AIO-Sandbox（Docker MCP） | ghcr.io/agent-infra/sandbox |
| 飞书 SDK | lark-oapi | ≥ 1.3 |
| LLM 客户端 | OpenAI-compatible（DeepSeek/Qwen） | — |

### 2.2 前端

| 组件 | 技术选型 | 版本 |
|------|----------|------|
| 框架 | React | 19.x |
| 构建工具 | Vite | 6.x |
| 样式 | Tailwind CSS | 4.x |
| 实时同步 | ElectricSQL | ≥ 1.5 |
| Markdown 渲染 | react-markdown + rehype-highlight | — |
| 测试 | Vitest + Testing Library | — |
| 语言 | TypeScript | 5.7 |

---

## 3. 分层架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                        接入层 (Transport Layer)                        │
│  ┌───────────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │ 飞书 Webhook  │  │ Web Frontend API │  │ Test API (dev only)   │  │
│  │  (Listener)   │  │  (aiohttp:8080)  │  │  (aiohttp:9090)      │  │
│  └───────┬───────┘  └────────┬─────────┘  └──────────┬────────────┘  │
└──────────┼───────────────────┼──────────────────────┼────────────────┘
           │                   │                      │
           ▼                   ▼                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      编排层 (Orchestration Layer)                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Runner（消息路由 + 队列管理 + Hook 事件分发 + EventBus 发布）    │  │
│  └────────────────────────────────┬───────────────────────────────┘  │
│                                   │                                   │
│  ┌───────────────────┐  ┌────────┴────────┐  ┌───────────────────┐  │
│  │   SessionManager  │  │  MemoryAwareCrew │  │    EventBus       │  │
│  │  (会话生命周期)    │  │  (Main Agent)    │  │  (事件分发总线)    │  │
│  └───────────────────┘  └────────┬────────┘  └───────────────────┘  │
└──────────────────────────────────┼───────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       能力层 (Capability Layer)                        │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐              │
│  │ SkillLoader  │  │ ModelRouter   │  │ KnowledgeSearch│             │
│  │ (技能加载)    │  │ (多模型路由)   │  │ (知识库检索)   │             │
│  └──────┬───────┘  └───────────────┘  └──────────────┘              │
│         │                                                            │
│  ┌──────┴───────┐                                                    │
│  │  Sub-Crew    │ ← AIO-Sandbox (Docker MCP)                        │
│  │ (沙箱执行)   │                                                    │
│  └──────────────┘                                                    │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       加固层 (Hardening Layer)                         │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  HookRegistry（5+2 事件体系）                                  │    │
│  │  ├─ 观测层 dispatch: structured_log, langfuse_trace           │    │
│  │  └─ 策略层 dispatch_gate: sandbox_guard, permission_gate,     │    │
│  │       cost_guard, loop_detector, retry_tracker, audit_logger  │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       存储层 (Storage Layer)                           │
│  ┌───────────────┐  ┌───────────────────┐  ┌───────────────────┐    │
│  │ SQLite        │  │ PostgreSQL+pgvector│  │ 文件系统           │    │
│  │ (auth.db)     │  │ (memories/skills/  │  │ (workspace/       │    │
│  │ 认证/团队/RBAC │  │  sessions/kb)      │  │  sessions/logs)   │    │
│  └───────────────┘  └───────────────────┘  └───────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. 核心模块详解

### 4.1 Runner（消息调度引擎）

**位置**：`xiaopaw/runner.py`

Runner 是整个系统的消息处理核心，采用 **per-routing_key 串行队列 + gen-counter worker 生命周期** 模式：

- **消息分发**：`dispatch(inbound)` → 按 `routing_key` 路由到对应队列
- **Worker 管理**：每个 routing_key 一个 worker task，空闲超时自动退出
- **Hook 集成**：在 turn 生命周期的关键节点触发 Hook 事件
- **EventBus 发布**：AGENT_STARTED / THINKING / AGENT_COMPLETE / AGENT_ERROR
- **斜杠命令**：拦截 `/new` `/help` `/status` `/verbose` 等控制命令
- **Expert/Skill Hints 注入**：叠加顺序为 `expert_prompt → hint_line → user_content`

```
消息处理流程：
dispatch → _worker → _handle → [slash?] → session → hook(BEFORE_TURN)
  → send_thinking → pre-flight(sandbox_guard) → agent_fn → hook(AFTER_TURN)
  → send_reply → persist → EventBus(AGENT_COMPLETE)
```

### 4.2 Agent 架构（Main Crew + Sub-Crew）

**位置**：`xiaopaw/agents/main_crew.py`

#### 4.2.1 Main Crew（MemoryAwareCrew）

基于 CrewAI 框架的主编排 Agent，职责：

- **Bootstrap 角色注入**：从 `workspace/*.md` 构建 backstory 人格提示
- **三层记忆上下文恢复**：会话首轮 LLM 调用前 `_restore_session` 注入历史
- **上下文管理**：`prune_tool_results` 精简旧轮工具结果 + `maybe_compress` Token 压缩
- **工具装配**：SkillLoaderTool + IntermediateTool + KnowledgeSearchTool
- **多模型路由**：通过 `model_router.get_llm(task_type="orchestrator")` 自动选模型
- **P3-1 多 Agent 协作**（feature flag）：规划→执行→审查三角色管线

#### 4.2.2 Sub-Crew（沙箱技能执行）

SkillLoaderTool 动态创建 Sub-Crew，在 Docker 沙箱中执行技能脚本：

- 读取 `SKILL.md` 解析 Agent/Task 配置
- MCP 协议连接沙箱（`http://localhost:8030/mcp`）
- 隔离执行环境：无法访问宿主文件系统（仅 `/workspace` 挂载点）

### 4.3 Hook 框架（5+2 事件体系）

**位置**：`xiaopaw/hook_framework/`

#### 4.3.1 事件类型

| 事件 | 触发时机 | 用途 |
|------|----------|------|
| BEFORE_TURN | 消息进入 Runner | 日志/追踪初始化 |
| BEFORE_LLM | LLM 调用前 | Token 统计/模型记录 |
| BEFORE_TOOL_CALL | 工具执行前 | **安全拦截点**（sandbox_guard/permission_gate） |
| AFTER_TOOL_CALL | 工具执行后 | 循环检测/重试追踪 |
| AFTER_TURN | 轮次结束 | 成本计算/审计 |
| TASK_COMPLETE | Task 完成 | CrewAI 回调 |
| SESSION_END | 会话结束 | Langfuse flush/审计摘要 |

#### 4.3.2 两套分发机制

- **dispatch（报警器模式）**：异常吞掉不影响业务，用于观测层（structured_log/langfuse_trace）
- **dispatch_gate（保险丝模式）**：`GuardrailDeny` 穿透阻断业务，用于策略层

#### 4.3.3 策略组件

| 组件 | 职责 | fail_closed |
|------|------|-------------|
| sandbox_guard | 沙箱逃逸检测 + prompt 注入防护 | ✅ |
| permission_gate | RBAC 细粒度权限控制 | ✅ |
| cost_guard | 单 turn 成本预算 ($1.0) | ❌ |
| loop_detector | 重复输出/死循环检测 (threshold=3) | ❌ |
| retry_tracker | 工具重试次数限制 (max=5) | ❌ |
| audit_logger | 安全审计日志 (security_audit.jsonl) | ❌ |

### 4.4 EventBus（事件总线）

**位置**：`xiaopaw/event_bus.py`

轻量级发布/订阅事件总线，解耦 Agent 编排层与传输层：

- **AgentEvent**（9 种）：agent_started / streaming / complete / error / tool_call_start / tool_call_result / session_created / title_updated / thinking
- **CommunityEvent**（8 种）：skill_published / approved / rejected / installed / reviewed / featured / suspended / ranking_updated
- **订阅者**：ActivityRecorder（全量记录）、NotificationService（审核通知）、WebSocket 推送
- **设计特点**：handler 异常不影响其他 handler；支持全局 `"*"` 订阅和 session 级过滤

### 4.5 多模型路由（ModelRouter）

**位置**：`xiaopaw/llm/model_router.py`

#### 4.5.1 任务类型分类

| TaskType | 说明 | 典型模型 |
|----------|------|----------|
| ORCHESTRATOR | Main Crew 主编排 | deepseek-v4-flash |
| SKILL_EXECUTION | Sub-Crew 技能执行 | deepseek-v4-flash |
| MEMORY_INDEXING | 记忆摘要/嵌入 | deepseek-chat |
| CODE_GENERATION | 代码生成 | — |
| GENERAL_CHAT | 通用对话 | — |
| MULTIMODAL | 多模态理解 | — |

#### 4.5.2 路由策略

| 策略 | 选择逻辑 |
|------|----------|
| COST_FIRST | 选最便宜的可用模型 |
| QUALITY_FIRST | 选能力最强的模型 |
| LATENCY_SENSITIVE | 选响应最快的模型 |
| ROUND_ROBIN | 轮询均衡 |
| PRIORITY | 按配置顺序尝试 |
| COMPLEXITY_BASED | **复杂度自适应**（启发式评分 → 自动选档） |

#### 4.5.3 复杂度自适应

`estimate_prompt_complexity(prompt)` 根据长度、代码块、关键词、多步标记等维度评分：
- ≥ 0.66 → QUALITY_FIRST（高质量模型）
- ≥ 0.33 → LATENCY_SENSITIVE（平衡模型）
- < 0.33 → COST_FIRST（低成本模型）

### 4.6 三层记忆体系

| 层级 | 存储 | 作用 |
|------|------|------|
| Bootstrap | 文件系统 `workspace/*.md` | 角色人格/用户画像/长期记忆注入 backstory |
| Session Context | 文件系统 `data/ctx/` | 多轮对话上下文持久化（跨重启恢复） |
| Semantic Memory | PostgreSQL + pgvector | 向量语义检索 + 全文检索（HNSW + tsvector） |

**索引流程**：每轮结束 → `async_index_turn` → LLM 摘要 → text-embedding-v3 嵌入(dim=1024) → upsert 到 `memories` 表

### 4.7 知识库（Knowledge Base RAG）

**位置**：`xiaopaw/knowledge/`

- **知识库管理**：personal/org 两级隔离，支持文件/URL/飞书文档导入
- **处理管线**：上传 → pending → processing（解析/分块/嵌入）→ ready
- **混合检索**：向量相似度（HNSW cosine）+ 全文检索（tsvector）
- **会话绑定**：`session_knowledge_bases` 表限定检索范围

### 4.8 技能体系

**位置**：`xiaopaw/skills/` + `xiaopaw/skills_mgmt/`

#### 4.8.1 内置技能（13 个）

| 技能 | 功能 |
|------|------|
| memory-save | 持久化记忆到 workspace |
| search_memory | 向量语义记忆检索 |
| baidu_search | 百度搜索引擎 |
| web_browse | 网页浏览/内容提取 |
| pdf | PDF 文档生成/解析 |
| docx | Word 文档处理 |
| xlsx | Excel 数据分析 |
| pptx | PPT 演示文稿生成 |
| feishu_ops | 飞书文档/日历操作 |
| scheduler_mgr | 定时任务管理 |
| history_reader | 历史对话回顾 |
| memory-governance | 记忆治理/清理 |
| skill-creator | 自定义技能创建 |

#### 4.8.2 技能市场

- **SkillRegistry**：管理 builtin + user 技能的元数据和启用状态
- **MarketRegistry**：远程技能仓库（Vercel Skills + ClawHub）索引与安装
- **CommunityRegistry**：社区发布/审核/评价/排行系统
- **会话级技能选择**：`session_skills` 表支持按会话启用特定子集
- **@ 引用**：前端 `@技能名` → `skill_hints` → Runner 注入优先加载指令

---

## 5. 数据库设计

### 5.1 混合存储策略

| 存储引擎 | 用途 | 选型理由 |
|----------|------|----------|
| SQLite (auth.db) | 认证/用户/团队/组织/专家/自动化 | 零依赖部署、嵌入式、WAL 高并发读 |
| PostgreSQL + pgvector | 记忆/会话/知识库/技能市场/社区/通知 | 向量索引(HNSW)/全文检索/ACID/多租户 |
| 文件系统 | 会话上下文/workspace/日志/技能脚本 | 快速读写、沙箱挂载兼容 |

### 5.2 PostgreSQL 核心表

```
memories              -- 语义记忆（vector(1024) + tsvector 混合检索）
conversations         -- 对话消息流水
sessions              -- 会话元数据（routing_key + org_id + team_id 多维隔离）
skills                -- 技能元数据
session_skills        -- 会话-技能绑定
skill_market          -- 远程技能市场索引缓存
community_skills      -- 社区发布技能（审核/评分/安装追踪）
skill_reviews         -- 技能评价
skill_categories      -- 技能分类字典
user_favorites        -- 用户收藏
users                 -- 用户镜像（FK 引用）
agent_activities      -- Agent 活动流水（可视化/分析）
notifications         -- 站内通知
knowledge_bases       -- 知识库
knowledge_documents   -- 文档
knowledge_chunks      -- 分块 + 嵌入（vector(1024)）
session_knowledge_bases -- 会话-知识库绑定
```

### 5.3 索引策略

- **HNSW 向量索引**：`m=16, ef_construction=64`（cosine 距离）
- **GIN 全文索引**：`to_tsvector('simple', ...)` 中文友好
- **GIN 数组索引**：tags 标签查询
- **B-tree 时间索引**：`created_at DESC` 时序查询

---

## 6. 多租户与权限模型

### 6.1 租户隔离

```
routing_key: "p2p:web_{username}"  → 个人隔离
org_id: BIGINT                      → 组织隔离
team_id: INTEGER                    → 团队共享
```

### 6.2 RBAC 角色权限

- **角色解析**：`Runner.role_resolver` → `resolve_rbac_role(user_auth, sender_id)`
- **权限执行**：`permission_gate` Hook，支持 per-tool 级 allow/deny/warn
- **叠加语义**：角色仅收紧不放松（base 权限 + 角色限制 = 最终权限）

---

## 7. 可观测性

### 7.1 日志

- **结构化日志**：`structured_log` Hook → JSON 格式输出到 `data/logs/`
- **Trace ID 贯穿**：每条消息分配唯一 trace_id，跨模块传播

### 7.2 追踪

- **Langfuse 全链路追踪**：`langfuse_trace` Hook 在每个事件节点记录 span
- **事件链**：BEFORE_TURN(trace 创建) → BEFORE_LLM(generation) → BEFORE_TOOL_CALL(span) → AFTER_TOOL_CALL → SESSION_END(flush)

### 7.3 指标

- **Prometheus Metrics Server**：`:8090` 暴露指标
- **关键指标**：`agent_latency`（p50/p95/p99）、`inbound_total`（消息计数）

### 7.4 安全审计

- `audit_logger` → `data/logs/security_audit.jsonl`
- 记录所有安全相关事件（deny/allow/warn）及元数据

---

## 8. 部署架构

### 8.1 组件拓扑

```
┌─────────────────────────────────────────────────┐
│                  宿主机 (macOS/Linux)             │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │         XiaoPaw 主进程 (Python)             │  │
│  │  ├─ Frontend API   :8080                   │  │
│  │  ├─ Metrics        :8090                   │  │
│  │  ├─ Test API       :9090 (dev)             │  │
│  │  ├─ Feishu Listener (webhook)              │  │
│  │  └─ Background Tasks (cron/cleanup/sync)   │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │       AIO-Sandbox (Docker)                  │  │
│  │  ├─ 127.0.0.1:8030 → :8080 (MCP)          │  │
│  │  ├─ /workspace 挂载 ./data/workspace       │  │
│  │  ├─ /mnt/skills 挂载 ./xiaopaw/skills      │  │
│  │  └─ 资源限制: 2G RAM / 2 CPU               │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │       PostgreSQL + pgvector                 │  │
│  │  └─ memories/sessions/skills/knowledge...   │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │       Vite Dev Server (开发环境)             │  │
│  │  └─ localhost:5173 → proxy /api → :8080    │  │
│  └────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

### 8.2 沙箱安全加固

| 措施 | 说明 |
|------|------|
| 端口绑定 | `127.0.0.1:8030` 仅本地访问 |
| 能力移除 | `cap_drop: ALL` + 仅保留 `NET_BIND_SERVICE` |
| 特权限制 | `no-new-privileges: true` |
| 资源限制 | 2G 内存 / 2 CPU 上限 |
| 健康检查 | 每 10s 探活，连续 3 次失败重启 |
| 挂载隔离 | 仅 workspace + skills 目录可写 |

### 8.3 启动流程

```
main() 启动序列：
1. load_config() → 加载 config.yaml
2. _init_model_router() → 多模型路由初始化
3. setup_logging() → 结构化日志配置
4. assert_all_production_safe() → 生产安全检查
5. _prewarm_crewai_storage() → CrewAI 存储预热
6. PGStore + SearchService → PostgreSQL 连接
7. EventBus + ActivityRecorder → 事件订阅
8. NotificationService → 通知订阅
9. _build_skill_layers() → 技能三层初始化
10. SessionManager → 会话管理
11. build_agent_fn() → Agent 工厂函数
12. HookLoader.load_two_layers() → Hook 加载
13. Runner → 核心调度引擎
14. start_metrics_server() → Prometheus 指标
15. CronService → 定时任务
16. CleanupService → 数据清理
17. Frontend / Feishu Listener → 接入层启动
18. _probe_sandbox() → 沙箱探活
19. signal wait → 等待关闭信号
```

---

## 9. 数据流向

### 9.1 Web 前端消息处理流

```
用户输入 → React UnifiedInputBar
  → extractSkillHints(@技能解析)
  → POST /api/frontend/sessions/{id}/messages/stream
  → _sanitize_skill_hints (max 3, len ≤ 64)
  → InboundMessage(content, skill_hints, expert_prompt)
  → Runner.dispatch()
  → Worker._handle()
    → Hook: BEFORE_TURN
    → send_thinking (SSE: {"type":"thinking"})
    → Pre-flight: sandbox_guard
    → agent_input = expert_prompt + hint_line + content
    → MemoryAwareCrew.run_and_index()
      → before_llm_hook: 上下文恢复/压缩
      → CrewAI akickoff → LLM 推理循环
        → before_tool_hook: 安全检查
        → SkillLoaderTool → Sub-Crew(sandbox)
      → async_index_turn: 记忆索引
    → Hook: AFTER_TURN
    → SSE: {"type":"delta"} chunks + {"type":"done"}
    → EventBus: AGENT_COMPLETE
    → PG persist (conversations + sessions)
```

### 9.2 记忆检索流

```
search_memory 技能调用：
  → routing_key 租户隔离
  → text-embedding-v3 查询向量化
  → PostgreSQL 混合检索:
    ├─ vector: summary_vec <=> query_vec (cosine, HNSW)
    ├─ fulltext: search_tsv @@ to_tsquery(keywords)
    └─ RRF 融合排序
  → Top-K 结果返回 Agent
```

---

## 10. 配置体系

配置文件 `config.yaml` 覆盖所有运行时参数，支持环境变量 `${VAR}` 替换：

| 配置段 | 说明 |
|--------|------|
| `workspace` / `data_dir` | 数据目录 |
| `feishu` | 飞书应用凭证 + 允许群列表 |
| `agent` | 模型/迭代次数/超时/子 Agent 配置 |
| `sandbox` | 沙箱 MCP URL + 超时 |
| `memory` | PG DSN + 压缩阈值 + Token 窗口 |
| `session` | 最大活跃会话 + 历史轮次 |
| `runner` | 队列大小 + 空闲超时 |
| `sender` | 重试策略 + 并发限制 |
| `frontend` | Web 服务端口 |
| `observability` | Metrics + Langfuse |
| `cron` | 定时任务开关 + 间隔 |
| `cleanup` | 数据清理 TTL |
| `skills` | 技能目录 + 上传限制 |
| `feature_flags` | 功能开关（12 个） |

---

## 11. Feature Flags

| Flag | 默认 | 说明 |
|------|------|------|
| `token_counter_mode` | "rough" | Token 计数模式 |
| `enable_skill_timeout` | true | 技能执行超时 |
| `enable_cron_filelock` | true | Cron 文件锁 |
| `enable_memory_save_filelock` | true | 记忆写入文件锁 |
| `enable_trace_id` | true | Trace ID 追踪 |
| `enable_mcp_whitelist` | true | MCP 工具白名单 |
| `enable_memory_save_filter` | true | 记忆保存过滤 |
| `enable_webhook_replay_cache` | true | Webhook 去重缓存 |
| `enable_inbound_rate_limit` | true | 入站限流 |
| `enable_multi_agent_collab` | false | 多 Agent 协作管线 |

---

## 12. 安全设计

### 12.1 威胁模型

| 威胁 | 对策 |
|------|------|
| Prompt 注入 | sandbox_guard 特征检测 + MCP 白名单 |
| 沙箱逃逸 | Docker 能力移除 + 路径白名单 + seccomp |
| 成本超支 | cost_guard 预算阈值 ($1.0/turn) |
| 死循环 | loop_detector (threshold=3) + retry_tracker (max=5) |
| 重放攻击 | ReplayCache (TTL=300s, maxsize=10000) |
| 暴力破解 | RateLimiter (20 req/user/min) |
| 越权访问 | permission_gate RBAC + routing_key 隔离 |
| 数据泄露 | 多租户隔离（routing_key/org_id/team_id） |

### 12.2 安全组件 fail-closed 语义

`sandbox_guard` 和 `permission_gate` 标记为 `fail_closed=True`：自身崩溃时默认拒绝（宁可错杀不可放过）。

---

## 13. 后台服务

| 服务 | 周期 | 职责 |
|------|------|------|
| CronService | 30s 检查 | 自动化定时任务调度 |
| CleanupService | 每日 03:00 UTC | 过期会话/追踪/原始数据清理 |
| MarketSync | 每 6h | 远程技能市场索引同步 |
| CommunityStats | 每 1h | 社区技能统计聚合 |
| CommunityCleanup | 每 1d | 社区数据清理 |

---

## 14. 扩展性设计

### 14.1 新渠道接入

得益于 EventBus 解耦，新增传输渠道（钉钉/微信/Slack）只需：
1. 实现 `SenderProtocol`（4 个方法）
2. 订阅 EventBus 事件接收推送
3. 构造 `InboundMessage` 调用 `Runner.dispatch()`

### 14.2 新技能开发

编写 `SKILL.md`（声明式 Agent/Task/Tool 配置）放入 `xiaopaw/skills/{name}/` 或用户目录即可。SkillLoaderTool 自动发现并在沙箱中执行。

### 14.3 新 Hook 开发

1. 在 `shared_hooks/` 下编写 handler 函数
2. 在 `hooks.yaml` 中声明事件绑定
3. HookLoader 自动加载（观测层用 dispatch，策略层用 dispatch_gate）

---

## 15. 测试体系

| 层级 | 框架 | 范围 |
|------|------|------|
| 单元测试 | pytest | Hook/Model/Utils/Memory |
| 集成测试 | pytest + TestAPI | Runner/Session/Export/Agent |
| E2E 测试 | pytest + TestAPI | 完整消息链路（15 个场景） |
| 前端测试 | Vitest + Testing Library | 组件/交互/@ 引用 |
| 安全测试 | pytest (marker: security) | 沙箱逃逸/注入/权限 |

**测试标记**：`integration` / `llm_dependent` / `sandbox` / `pgvector_required` / `security` / `e2e` / `full`

# 会话知识库绑定与聊天文件上传 设计文档

日期：2026-07-08
状态：已确认（用户批准方案 A）
前置：知识库 RAG P0 已上线（建库/上传/摄取/混合检索/Agent 工具 `search_knowledge_base`/引用溯源）

## 1. 需求

1. **知识库加入工具菜单**：会话输入框底部工具栏（专家/技能按钮旁）新增「知识库」按钮，用于查看和绑定当前会话引用的知识库。
2. **会话引用知识库**：会话绑定知识库后，Agent 的 `search_knowledge_base` 检索**限定**在绑定库内；未绑定时保持现状（检索全部个人可见库）。
3. **会话窗口文件上传**：启用输入框附件按钮，上传的文件**进入知识库**（走现有摄取管线，之后可被检索引用）；会话无绑定库时**自动创建个人库并绑定**。

## 2. 方案选型（已定：方案 A —— 服务端绑定表）

复用 P0 预留的 `session_knowledge_bases` 表与 `KnowledgeStore.set_session_bases()/get_session_bases()`（schema.sql L400-408、store.py L279-295，均已存在但未接线）。

放弃的备选：
- B（随消息传 kb_ids，仿 expert out-of-band）：绑定仅存客户端、不跨设备，且需改 InboundMessage/_prepare_message/runner/crew 四层。
- C（sessions 表加 metadata JSONB）：需迁移表结构，且与已有绑定表重复建设。

选 A 的理由：表和 store 方法现成、绑定服务端持久化、**消息发送链路（payload/InboundMessage/runner）零改动**。

## 3. 数据与检索层

**不改 schema。**

检索链扩展为支持多库限定（向后兼容）：

- `xiaopaw/knowledge/store.py` `search_candidates()`：新增 `kb_ids: list[str] | None = None` 参数；SQL 条件由 `AND c.kb_id = %(kb_id)s` 扩展为 `AND c.kb_id = ANY(%(kb_ids)s)`。原 `kb_id` 参数保留，内部归一为单元素列表；`kb_id` 与 `kb_ids` 同时传时 `kb_ids` 优先。租户过滤 SQL（owner_key/org_id）保持不变，kb_ids 仅在可见集内收窄。
- `xiaopaw/knowledge/retriever.py` `retrieve()`：同样新增 `kb_ids` 参数，透传给 `search_candidates`。

## 4. 后端 API（2 个新端点）

注册于 `xiaopaw/frontend/routes/session.py`：

### GET /api/frontend/sessions/{session_id}/knowledge-bases
返回 `{ "kb_ids": [...], "bases": [完整库对象...] }`（bases 为 kb_ids 对应的、仍对调用者可读的库详情；已删除或失去权限的库从结果中剔除）。

### PUT /api/frontend/sessions/{session_id}/knowledge-bases
Body `{ "kb_ids": ["kb-xxx", ...] }`，**全量替换**绑定（空数组 = 解绑全部）。

两端点共同的校验链：
1. `check_auth`（401）
2. 会话 IDOR 校验：复用 `_find_owning_routing_key` 模式——会话不存在返回 404；归属他人且非团队共享返回 404；共享会话的 PUT 需 `edit` 权限（403）
3. PUT 专属：逐个 kb_id 调 `KnowledgeStore.can_access` 校验对调用者可读，任一不可读返回 403；`len(kb_ids) > 5` 返回 422（防滥用上限）

## 5. Agent 链路（限定检索）

- `xiaopaw/tools/knowledge_search_tool.py` `KnowledgeSearchTool` 新增构造注入字段 `allowed_kb_ids: list[str] | None = None`（与 routing_key/db_dsn 同为构造注入，LLM 不可伪造）：
  - `None` 或空列表 → 行为不变（检索全部个人可见库）
  - 非空 → `retrieve(kb_ids=allowed_kb_ids)` 限定检索；若 LLM 传入的 `kb_id` 在白名单内则单库检索，不在白名单内则忽略该参数、回落到白名单整体检索，并在返回文本首行附提示（不抛错、不中断）
  - 非空时 `description` 动态追加「当前会话已绑定 N 个知识库，检索将限定在绑定范围内」
- `xiaopaw/agents/main_crew.py` `orchestrator()`：构造 KnowledgeSearchTool 前执行 `KnowledgeStore(self._db_dsn).get_session_bases(self.session_id)` 获取绑定；整体 try/except 包裹，读取失败记 warning 并降级为 `None`（不阻塞会话）。`_db_dsn` 为空时跳过读取。

## 6. 前端 UI（均仅 chat 模式生效，与「技能」按钮同模式）

### 6.1 「知识库」按钮（`frontend/src/components/UnifiedInputBar.tsx`）
- 位置：底部工具栏，专家/技能按钮旁；样式对齐 SkillButton
- 点击弹 popover：列出个人库（名称 + 文档数，复选框多选），确认时调 PUT 绑定 API；打开时用 GET 回显当前绑定
- 有绑定时按钮高亮并带数量徽标（如「知识库 ·2」）

### 6.2 附件按钮启用
- 去掉 disabled；`accept=".pdf,.docx,.md,.markdown,.txt,.text"`，多选，单文件 ≤ 32MB（与后端限制一致，前端预检）
- 上传目标：会话已有绑定 → 第一个绑定库；无绑定 → `createBase({name: "会话资料 MM-DD", scope: "personal"})` → PUT 绑定 → 上传（全部复用现有 API）
- 无活动会话（isHome 或 sessionId 为 null）时附件与知识库按钮不渲染

### 6.3 上传状态芯片（仿专家芯片，输入框上方）
- 生命周期：`📎 文件名 上传中… → 解析中… → ✓ 已就绪可引用`；轮询 `getDocument` status（3s 间隔），ready/failed 后停止
- failed：芯片转红显示「解析失败」，正文提示到知识库页面查看详情；可点 ✕ 移除芯片（不删文档）

### 6.4 API 客户端（`frontend/src/api/knowledge.ts`）
新增 `getSessionBases(sessionId)` / `setSessionBases(sessionId, kbIds)`。

## 7. 错误处理

| 场景 | 行为 |
|------|------|
| 绑定 API：库不可读 | 403，前端 popover 内提示 |
| 绑定 API：会话不存在/无权 | 404 |
| 绑定 API：超 5 个库 | 422 |
| 上传：类型/大小不符 | 前端预检拦截；后端 415/413 兜底，芯片转红 |
| 上传：网络失败 | 芯片转红显示错误，可移除，不打断输入 |
| 摄取 failed | 芯片显示解析失败 + 引导去知识库页面 |
| Agent 读绑定失败 | 日志 warning，降级为不限定检索，会话不受影响 |

## 8. 测试

- **单元测试**
  - `search_candidates`/`retrieve`：`kb_ids` 过滤三态（多库列表 / 空列表按 None 处理 / None 不限定）；`kb_id` 与 `kb_ids` 并存时的优先级
  - `KnowledgeSearchTool`：`allowed_kb_ids` 白名单裁决（kb_id 在/不在白名单、空白名单回落）
  - 绑定 API 权限矩阵：自己的会话 / 他人会话 404 / 共享会话 view=403·edit=200 / 不可读库 403 / 超限 422 / 空数组解绑
- **集成测试**：设置绑定 → 构造 crew → 验证 KnowledgeSearchTool 只命中绑定库内容
- **E2E**（复用 kbe2e 账号资产）：聊天上传 README → 自动建库并绑定 → 状态芯片走到就绪 → 提问 → 回答带 [编号] 且引用来自绑定库

## 9. 明确不做（YAGNI）

- 上传文件「仅本次会话使用」（工作区模式）——后续迭代
- 组织库在聊天内的绑定检索（Agent 工具当前 org_id 未注入，维持 P0 个人库范围；绑定 popover 仅列个人库）
- 自动预检索注入上下文（P1 备选，本期不做）
- 语音按钮（保持禁用）

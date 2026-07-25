# 统一 @ 引用（专家 + 技能）设计

- 日期：2026-07-08
- 状态：已确认（方案 B：结构化提示注入）
- 前置：会话知识库绑定与聊天文件上传（2026-07-08-session-knowledge-binding-design.md）

## 1. 目标与范围

会话窗口输入 `@` 弹出统一浮层，两栏：**专家 / 技能**。

- 选专家 = 现行为不变：激活为会话专家，@token 从输入框移除
- 选技能 = 在光标处插入 `@技能名 ` 字面 token；发送时解析为 `skill_hints`
  结构化字段，指示 Agent **本条消息**优先使用该技能（不改变会话级技能绑定）

不做（YAGNI）：

- 知识库/文档的 @ 引用
- textarea 富文本高亮（token 为纯文本，用户可直接编辑删除）
- 首页改动（isHome 时 @ 维持专家单栏现状）
- skill_hints 持久化（本条消息瞬时语义）

## 2. 方案取舍

| 方案 | 说明 | 结论 |
|------|------|------|
| A 纯文本约定 | @token 原样发给 LLM，靠模型自觉 | 遵守率不可控，弃 |
| **B 结构化提示注入** | 前端解析 hints 随消息提交，后端注入显式指令行 | **采用** |
| C 强制预载执行 | hints 绕过 orchestrator 强制执行技能 | 破坏自主调度架构，弃 |

选 B 理由：遵守率高（显式指令）、改动集中（协议一个可选字段 + runner 一处注入）、
强制点复用 SkillLoaderTool 现有 `enabled_skills` 白名单，与知识库 `allowed_kb_ids`
的构造注入风格同构。

## 3. 前端交互

### 3.1 MentionPicker（新组件 `frontend/src/components/MentionPicker.tsx`）

- 两栏 Tab（专家 / 技能）；专家栏复用 `ExpertPickerList`
- 技能栏数据源与 SessionSkillsPicker 一致：`GET /skills` +
  `GET /sessions/{sid}/skills`，**只列会话启用的技能**（无绑定行 = 全部启用）
- `mentionQuery`（@ 后输入的文字）同时过滤两栏；键盘上下/回车选择

### 3.2 UnifiedInputBar 改动

- `!isHome` 时 @ 浮层由 `ExpertPickerPopover` 换为 `MentionPicker`；
  isHome 保持专家单栏
- 选技能：`@token` 替换为 `@技能名 `（尾随空格），token 留在文本中
- `handleSend` 提取 hints：正则匹配文本中的 `@(\S+)`，与启用技能名**精确匹配**
  才计入；去重、最多 3 个；消息正文原样保留 @ 字样
- `onSend` 签名扩展：`onSend(text, opts?: { skillHints?: string[] })`；
  App.tsx 透传到 API body（不传时字段省略）

## 4. 协议与后端

### 4.1 协议

`POST /api/frontend/message` 与 `/api/frontend/message/stream` 请求体新增可选字段：

```json
{ "content": "...", "session_id": "...", "expert": "...", "skill_hints": ["skill-a"] }
```

### 4.2 `_prepare_message`（xiaopaw/frontend/routes/session.py）

形状校验（宽容策略，绝不因 hints 报错）：

- 非 list → 整体忽略
- 逐项：非 str / 空串 / 长度 > 64 → 丢弃该项
- 去重后截断至前 3 个
- 结果存入 `InboundMessage.skill_hints`

### 4.3 模型（xiaopaw/models.py）

`InboundMessage` 新增字段：`skill_hints: list[str] = field(default_factory=list)`。

### 4.4 注入（xiaopaw/runner.py）

在现 expert_prompt 合成处（agent 输入前置，不影响持久化内容）：

```
（用户为本条消息指定了优先使用技能：{", ".join(hints)}。
请先通过 skill_loader 加载并使用它处理本条消息，除非明显不适用。）
```

与 expert_prompt 叠加时顺序：expert_prompt → hint 行 → 用户内容。

## 5. 安全与降级

- **强制点在 SkillLoaderTool 的 `enabled_skills` 白名单**：hint 未启用/不存在的
  技能时工具拒载，Agent 自然回落。路由层不查白名单（省一次 DB 读）
- hints 不持久化；消息正文持久化原文（含 @ 字样），会话标题逻辑不变
- 旧前端/飞书通道不传该字段 → 行为完全不变（默认空列表）
- hints 指令是提示而非强制，与 orchestrator 自主调度兼容

## 6. 测试计划

- 单测（tests/unit）：
  - `_prepare_message` skill_hints 校验矩阵：合法 / 非 list / 项非 str / 空串 /
    超长项 / 超过 3 个 / 重复项
  - runner 注入格式：仅 hints、hints + expert_prompt 叠加、无 hints 原样
- 前端：hints 提取纯函数用例（精确匹配 / 不在启用集 / 去重 / 上限 3）+
  MentionPicker 渲染测试；`npm run build` 通过
- E2E 手测：会话中 `@某技能 <任务>` 发送 → 结构化日志确认
  `before_tool_call: skill_loader` 且加载的是指定技能

# 在对话框中使用/召唤专家 —— 设计文档

- 日期：2026-07-08
- 状态：已确认（待用户 review）
- 范围：在聊天输入框中直接选择/召唤专家，并修复专家上下文注入污染历史与标题的问题。

## 1. 背景与现状

后端已完整支持"专家召唤"：发送消息时若 payload 带 `expert`，`routes/session.py` 会查出该专家的 `system_prompt` 并注入到本条消息。前端目前只能在「专家」页点"召唤此专家"设置一个**全局** `activeExpert`（存 localStorage），随后静默随每条消息发送；聊天输入框内**没有任何专家入口**，也看不到当前激活的是哪位专家、无法切换或取消。

同时存在一个既有副作用：后端把 `[Expert: X]\n{system_prompt}\n\n---\n\n{原文}` 整体写入 `content`，而 `_persist_exchange` 以 `content` 落库用户消息、并用 `title=content[:80]` 生成会话标题——导致刷新/重开历史时用户气泡夹着大段系统提示、会话标题也被污染。专家入口做进对话框后该问题会被高频触发。

## 2. 目标

1. 在首页与会话内的统一输入框中，都能通过**「专家」按钮**或输入 **`@`** 快捷选择/召唤专家。
2. 被召唤专家**按会话独立**生效，新建任务默认无专家；当前专家以芯片形式可见、可一键取消。
3. 修复专家注入污染：用户可见文本与专家上下文解耦，落库消息与会话标题只保留用户原文。

## 3. 非目标（YAGNI）

- 历史消息气泡中"由某专家回答"的**持久化徽标**（需给 `conversations` 表加列、改动 PGStore），本次不做；实时会话通过输入框芯片体现当前专家即可。
- 不改动专家的 CRUD、精选场景、后端专家数据模型。
- 不引入后端会话级专家存储：专家选择由前端按会话保存并随每条消息重发，后端保持每条消息无状态。

## 4. 决策记录（Q1–Q5）

| # | 决策 |
|---|---|
| Q1 | 触发方式 = 底部「专家」按钮 + `@` 快捷，二者共用同一激活逻辑 |
| Q2 | 选择内容 = 按分类分组的专家列表 + 搜索框（`@` 用关键词实时过滤） |
| Q3 | 生效范围 = 每会话独立，新建任务默认无专家 |
| Q4 | 出现位置 = 首页 + 会话内输入框都显示 |
| Q5 | 一并修复专家注入污染历史/标题的问题（上下文与可见文本解耦） |

## 5. 状态模型与数据流（前端）

每会话专家用 localStorage 维护，避免误带到其他会话：

- `sessionExperts: Record<sessionId, expertName>`（持久化，键为会话 id）
- `pendingExpert: string | null`（尚未创建会话时——首页/新任务——暂存所选专家）
- 有效专家：`effectiveExpert = activeSessionId ? sessionExperts[activeSessionId] : pendingExpert`

流转：

1. 在输入框选中专家 → 有会话则写 `sessionExperts[id]`，否则写 `pendingExpert`。
2. 发送时 `payload.expert = effectiveExpert || undefined`（沿用现有字段，后端已认识）。
3. 首条消息创建新会话、返回 `session_id` 后 → 把 `pendingExpert` 迁移进 `sessionExperts[newId]` 并清空 `pendingExpert`。
4. 切换会话 → 芯片自动反映该会话的专家；✕ 取消 = 删除该会话的映射项。
5. 统一入口：「专家」页的"召唤此专家"按钮改为调用同一个 `selectExpert(name)` 句柄（写入当前上下文）并跳转到助手视图；废弃原全局 `active_expert` 单值。

刷新页面后映射仍在 localStorage，故专家选择可跨刷新保留。

## 6. 前端组件设计

### 6.1 新增 `ExpertPicker.tsx`（共享选择内容）

- 核心 `<ExpertPickerList query onSelect activeName authToken />`：顶部搜索框 + 按分类分组的专家列表（复用「专家」页已有的 `/experts`、`/expert-categories` 数据；小头像用现有 `ICON_EMOJIS`/`gradientOf`）。选中项高亮 `activeName`。
- 两种外壳共用这份列表：
  - 按钮浮层 `ExpertPickerPopover`：锚定底部「专家」按钮上方，天蓝配色，`Esc`/点击外部关闭。
  - `@` 内联浮层：锚定输入框上方，`query` = 用户在 `@` 之后键入的文字，实时过滤。

### 6.2 改造 `UnifiedInputBar.tsx`

- 新增 props：`activeExpert: string | null`、`onSelectExpert: (name: string | null) => void`、`authToken: string`。
- 底部工具栏加「专家」按钮（首页 + 会话内都显示，与现有 `SkillButton` 同款样式），点击开合 `ExpertPickerPopover`。
- `@` 触发：在 `handleInput` 中检测光标处正在输入的 `@token`（正则 `/(^|\s)@(\S*)$/`），命中则弹 `@` 内联浮层并以 `token` 过滤；选中专家后把 `@token` 从文本里删除并激活专家（`@` 只作唤起手势、不留字面文字，避免污染消息）。`Esc` 关闭。
- 当前专家芯片：文本框上方显示「🧠 当前专家：{display_name} ✕」，✕ → `onSelectExpert(null)`；无专家时不显示。
- 与现有 `/` 指令浮层互斥：`@` 浮层开启时不显示 `/` 浮层，反之亦然。

### 6.3 `App.tsx`

- 用第 5 节的每会话状态替换全局 `activeExpert`；导出 `effectiveExpert` 与 `selectExpert(name|null)`。
- 给两处 `UnifiedInputBar`（首页 `inputSlot` 与会话内）都传 `activeExpert={effectiveExpert}`、`onSelectExpert={selectExpert}`、`authToken`。
- `ExpertManagerView` 的 `onSelectExpert` 复用 `selectExpert`，`activeExpert` 传 `effectiveExpert`。

## 7. 后端改造（Q5：解耦，消除污染）

### 7.1 `models.py` — `InboundMessage` 新增字段

frozen dataclass，带默认值，向后兼容：

- `expert_prompt: str = ""` —— 专家系统提示（独立通道，不进 `content`）
- `expert_name: str = ""` —— 专家显示名（供可观测/日志，可选展示）

### 7.2 `routes/session.py` `_prepare_message` — 停止改写 `content`

- 删除现有把系统提示拼进 `content` 的逻辑。
- 改为：解析到 expert 后，`content` 保持用户原文；`expert["system_prompt"]` 放入 `InboundMessage.expert_prompt`、显示名放入 `expert_name`。
- 结果：`_persist_exchange` 落库的用户消息 = 原文；`title=content[:80]` = 原文首 80 字。历史与标题都干净。

### 7.3 `runner.py` `_handle` — 只在喂给 agent 时合成

- 调用 `self._agent_fn(...)` 前计算：
  `effective = f"{inbound.expert_prompt}\n\n---\n\n{inbound.content}" if inbound.expert_prompt else inbound.content`，仅把 `effective` 作为第一个入参传入。
- 其余全部仍用 `inbound.content`：slash 命令检测、`on_turn_start(user_message=...)`、EventBus、pre-flight `tool_input`。即 Agent 收到专家上下文，但展示/审计/事件看到的是用户原文。
- 飞书等其他来源不带 expert → `expert_prompt=""`，行为零变化。

## 8. 测试计划

- 后端单测：`_prepare_message` 带 `expert` → 返回的 `content` 为原文、`expert_prompt` 为该专家系统提示；无 `expert` → 行为如常。
- 后端集成（`test_scenario_api.py` 同款 TestClient + UserAuth）：POST `/api/frontend/message` 带 `expert=X` → 落库用户消息 == 原文（不含系统提示）、会话 `title` == 原文首段。
- runner 单测：构造带 `expert_prompt` 的 `InboundMessage`，桩 `agent_fn` 断言其收到 `effective`（含提示），而 `on_turn_start` 收到干净 `content`。
- 前端：`ExpertPickerList` 关键词过滤；`UnifiedInputBar` 显示/清除芯片、`@` 唤起并在选中后删除 `@token`、`/` 与 `@` 互斥；每会话切换芯片跟随。（沿用 `UnifiedInputBar.test.tsx` 现有测试基建）
- 验收：`pytest` 全绿；`npx tsc --noEmit` 通过；Playwright 视觉验证按钮浮层 + `@` 浮层 + 芯片 + 发送后历史/标题干净。

## 9. 影响文件清单

后端：
- `xiaopaw/models.py`（新增字段）
- `xiaopaw/frontend/routes/session.py`（解耦注入）
- `xiaopaw/runner.py`（喂 agent 时合成）

前端：
- `frontend/src/components/ExpertPicker.tsx`（新增）
- `frontend/src/components/UnifiedInputBar.tsx`（按钮/`@`/芯片）
- `frontend/src/App.tsx`（每会话状态 + 接线）

测试：
- `tests/unit/`（`_prepare_message`、runner 合成）
- `tests/integration/`（message 落库/标题干净）
- `frontend/src/components/UnifiedInputBar.test.tsx`（扩展）

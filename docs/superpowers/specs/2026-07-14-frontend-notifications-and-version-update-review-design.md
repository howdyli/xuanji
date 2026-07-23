# 前端打通：站内通知 + 版本更新复审 — 设计方案

- 日期：2026-07-14
- 状态：已实现
- 关联：
  - `docs/superpowers/specs/2026-07-14-skill-update-moderation-and-notifications-design.md`（后端能力）
  - `docs/system-architecture.md` 演进路线「技能版本更新纳入审核流程、审核通知」

## 背景与问题

后端已上线两项能力，但前端未接入，功能闭环缺失：

1. **站内通知无前端**：后端提供完整的拉取式通知 API（`GET /api/frontend/notifications`、
   `GET .../unread-count`、`POST .../{id}/read`、`POST .../read-all`），但 `DashboardTopBar`
   只有**两个静态铃铛图标**——其一错误地调用 `onOpenDrawer`（打开配置抽屉），其二无任何
   handler，且都显示一个硬编码红点角标。通知 API 完全未被调用。

2. **版本更新复审无前端区分**：后端 `list_pending` 现在同时返回首发待审与待审版本更新，行内
   含 `has_pending_update` / `pending_version` / `pending_install_url` 等字段（`SELECT *`）。
   但 `AdminReviewView` 的 `PendingSkill` 接口未读取这些字段，管理员无法区分「首发」与
   「版本更新」，也看不到 `v旧 → v新` 的产物变更。

## 目标

- 顶栏铃铛接入真实未读数与通知下拉面板，支持标记单条/全部已读。
- 审核面板区分并清晰呈现版本更新复审（标签 + 版本 diff + 安装地址变更）。
- 纯前端改动：后端 API 已就绪，**不改后端**。

## 非目标（YAGNI）

- 不做实时推送（SSE/WebSocket）通知；未读数用定时轮询。
- 不做独立通知全页、不做通知分页 UI（后端支持分页，前端本期只展示最近列表）。
- 不做通知偏好设置/免打扰。
- 不改 `list_pending` 排序或后端序列化。

## 设计

### 模块 A — 站内通知

纯前端，三处新增/改动 + App 传参。

**A1. 新增 hook `frontend/src/hooks/useNotifications.ts`**

封装通知数据与操作，暴露：

- `unreadCount: number`
- `notifications: NotificationItem[]`
- `loading: boolean`
- `refreshCount(): Promise<void>` — `GET /api/frontend/notifications/unread-count`
- `loadList(): Promise<void>` — `GET /api/frontend/notifications`（打开下拉时调用）
- `markRead(id): Promise<void>` — `POST .../{id}/read`，成功后乐观递减 `unreadCount` 并把该条置
  为已读
- `markAllRead(): Promise<void>` — `POST .../read-all`，成功后 `unreadCount=0`、列表全部置读

行为：

- 依赖 `authToken`；登录后每 **60s** 轮询 `refreshCount()`（对齐现有活动轮询节奏），组件卸载
  清理定时器。
- 所有 fetch 包 `try/catch`；失败或 503（store 未装配）静默降级为 `unreadCount=0` / 空列表，
  不抛错、不阻塞界面（呼应后端「DB 异常降级」设计）。

`NotificationItem` 形状（对齐后端 `_serialize`）：
`{ id: number; type: string; title: string; body: string; payload: Record<string, unknown>; read: boolean; created_at: string }`

**A2. 新增组件 `frontend/src/components/NotificationBell.tsx`**

- Props：`{ authToken: string }`
- 渲染铃铛按钮 + 未读角标（`unreadCount > 0` 时显示，`>99` 显示 `99+`；为 0 时不显示红点）。
- 点击铃铛切换下拉面板；打开时调用 `loadList()`。
- 下拉面板：
  - 顶部标题「通知」+「全部已读」按钮（`unreadCount > 0` 时可用）。
  - 列表：每条显示 `title`（加粗）、`body`、相对时间；未读条目左侧色条/背景高亮。
  - 点击单条 → `markRead(id)` 乐观更新。
  - 空态：「暂无通知」。
- 点击面板外部关闭（监听 document click / 使用一次性 outside-click 逻辑，沿用项目现有交互
  习惯）。

**A3. 改 `frontend/src/components/DashboardTopBar.tsx`**

- 新增 prop `authToken: string`。
- 首页视图（`isHome`）：用 `<NotificationBell authToken={authToken} />` 替换第 59-65 行那个
  无 handler 的静态铃铛按钮；保留搜索按钮与设置齿轮（齿轮继续 `onOpenDrawer`）。
- 非首页视图：把第 24-30 行错误调用 `onOpenDrawer` 的铃铛替换为 `<NotificationBell>`，并**补一个
  齿轮按钮**承接 `onOpenDrawer`（与首页一致，保证配置抽屉仍可打开）。

**A4. 改 `frontend/src/App.tsx`**

- 第 419 行 `<DashboardTopBar>` 增加 `authToken={authToken}` 传参（此处 `authToken` 已非空，
  因为已过登录门禁）。

### 模块 B — 版本更新复审

仅改 `frontend/src/components/market/AdminReviewView.tsx`；后端无需改动。

**B1. 扩展 `PendingSkill` 接口**，新增可选字段：

- `has_pending_update?: boolean`
- `pending_version?: string`
- `pending_install_url?: string`
- `install_url?: string`

**B2. 卡片区分呈现**

- `has_pending_update === true`（版本更新复审）：
  - 头部打**琥珀色「版本更新」标签**（替换/并列于原分类标签位置）。
  - 版本展示为 `v{version} → v{pending_version}`（旧 → 新）。
  - 若 `pending_install_url` 与 `install_url` 不同，展示一行「安装地址变更」，两值截断显示。
  - 备注输入 placeholder 改为「复审意见（可选）」；按钮文案「通过更新」「驳回更新」。
- `has_pending_update` 假值（首发待审）：**维持现状**（`v{version}` + 分类标签 + 通过/拒绝）。

**B3. moderate 调用不变**：仍 `POST .../admin/skills/{name}/moderate`，body `{action, note}`；
后端据 `has_pending_update` 自动走复审提升/丢弃分支。

## 数据流

```
铃铛挂载 ──60s──▶ GET unread-count ──▶ 角标
点开下拉 ──▶ GET notifications ──▶ 列表渲染
点条目 ──▶ POST {id}/read ──▶ 乐观递减 unreadCount + 置读
全部已读 ──▶ POST read-all ──▶ unreadCount=0 + 全部置读

审核面板 load() ──▶ GET admin/pending（含 pending_* 字段）──▶ 渲染层按 has_pending_update 区分
```

## 错误处理

- 沿用现有 `fetch + try/catch` 模式。
- 通知模块所有失败**静默降级**（角标归零 / 空列表），绝不阻塞主界面或弹错。
- 审核面板沿用现有 `error` 状态 + `fireToast` 提示。

## 测试

Vitest + Testing Library + jsdom，对齐现有 `LoginView.test.tsx` / `UnifiedInputBar.test.tsx` 模式，
`fetch` 用 mock。

- `NotificationBell.test.tsx`：
  - 未读数 > 0 渲染角标；为 0 不渲染红点。
  - 点击展开下拉并渲染列表条目。
  - 点击单条触发 `POST {id}/read`，未读数递减。
  - 「全部已读」触发 `POST read-all`，角标清零。
  - fetch 失败时不崩溃、角标为 0。
- `AdminReviewView.test.tsx`：
  - `has_pending_update` 卡片显示「版本更新」标签与 `v旧 → v新` diff。
  - 首发卡片维持原样（无「版本更新」标签）。

## 影响面与兼容性

- 改动集中在前端顶栏与审核面板；对话/工作台主流程不受影响。
- `DashboardTopBar` 新增必填 prop `authToken`，唯一调用点在 `App.tsx`（已同步修改）。
- 后端契约不变，向后兼容。

## 验收标准

1. 登录后顶栏铃铛显示真实未读数，60s 自动刷新。
2. 点击铃铛展开通知列表，可标记单条/全部已读，角标同步更新。
3. 配置抽屉在首页与非首页视图均可正常打开（齿轮按钮）。
4. 审核面板中版本更新条目带「版本更新」标签并显示版本 diff；首发条目呈现不变。
5. 新增前端测试全部通过，无回归。

# 技能版本更新纳入审核流程 + 审核通知 — 设计方案

- 日期：2026-07-14
- 状态：已实现
- 关联：`docs/system-architecture.md` 演进路线「技能版本更新纳入审核流程、审核通知」

## 背景与问题

技能市场当前存在两处缺口：

1. **版本更新绕过审核**：`CommunityRegistry.update_skill` 允许发布者直接修改已 `approved`
   技能的 `version`/`install_url` 等字段，无需再次审核。攻击者可先提交无害技能通过审核，
   随后把安装产物指向恶意内容，绕过审核门禁。

2. **无审核通知**：`moderate_skill` 仅通过 EventBus 发送瞬时事件（被 `ActivityRecorder`
   消费，且它只处理 `AgentEvent`、忽略 `CommunityEvent`）。发布者无法得知自己的技能被
   通过或驳回；没有任何按用户维度持久化、可拉取的通知。

## 目标

- 已通过技能的**安装产物变更**必须重新进入审核；审核期间线上继续服务旧的已通过版本，零中断。
- 审核通过 / 驳回时，向**发布者**落地一条可拉取的通知。

## 非目标（YAGNI）

- 不做管理员「有新待审提交」的通知（本次仅通知发布者）。
- 不引入异步消息队列；复用现有 EventBus + 同步订阅者模式。
- 不做飞书跨渠道推送；仅站内拉取式通知。
- 纯展示字段（description/icon 等）变更不触发复审。

## 关键决策（已与用户确认）

| 决策点 | 选择 |
| --- | --- |
| 复审触发范围 | 仅影响安装产物的字段（version / install_url / archive_hash） |
| 复审期可见性 | 继续展示旧的已通过版本（暂存列方案） |
| 通知落地方式 | 新建 `notifications` 表 + 拉取式 API |
| 通知接收方 | 仅发布者（审核通过 / 驳回） |

## 数据模型

所有变更以幂等 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 追加到 `schema.sql`。

### `community_skills` 新增暂存列

```sql
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_version       TEXT;
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_install_url   TEXT;
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_archive_hash  TEXT;
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS has_pending_update    BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE community_skills ADD COLUMN IF NOT EXISTS pending_submitted_at  TIMESTAMPTZ;
```

线上字段 `version/install_url/archive_hash/status` 语义不变；`pending_*` 仅暂存等待复审的
安装产物变更。

### 新增 `notifications` 表

```sql
CREATE TABLE IF NOT EXISTS notifications (
    id          BIGSERIAL PRIMARY KEY,
    recipient   TEXT NOT NULL,            -- username
    type        TEXT NOT NULL,            -- 'skill_approved' | 'skill_rejected'
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {skill_name, reviewer, note, is_update}
    read        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient
    ON notifications (recipient, read, created_at DESC);
```

## 版本更新纳入审核

修改 `xiaopaw/skills_mgmt/community.py`。

### 字段分类

- **产物字段** `{version, install_url, archive_hash}`
- **展示字段** `{description, category, tags, icon_url, screenshots, repo_url, license}`

`archive_hash` 加入 `update_skill` 允许集合（此前未允许），以支持发布者把 install_url
指向新内容时同步更新校验哈希。

### `update_skill(name, publisher, updates)`

1. 校验发布者归属（沿用现有 `WHERE name=%s AND publisher=%s`）。
2. 拆分 updates 为展示字段与产物字段。
3. **展示字段始终立即写入线上行**（无论 status）。
4. 产物字段处理：
   - 若技能当前 `status='approved'` 且存在产物字段变更：写入 `pending_*`、置
     `has_pending_update=TRUE`、`pending_submitted_at=NOW()`；**不改动线上 version/install_url/
     archive_hash 与 status**。
   - 否则（`pending`/`rejected`，无已通过版本需保护）：产物字段直接写入线上行；若原状态为
     `rejected`，重置为 `pending` 以重新排队。
5. 返回更新后的行。无有效字段时抛 `CommunityError("no_fields")`；非发布者抛 `not_owner`。

> 注：`update_skill` 本身不发通知事件（更新提交不通知发布者，避免自我通知噪音）。

### `list_pending`

查询条件由 `status='pending'` 扩展为：

```sql
WHERE status = 'pending' OR has_pending_update = TRUE
ORDER BY COALESCE(pending_submitted_at, created_at) ASC
```

使首次待审与待审更新进入同一审核队列。

### `moderate_skill(name, action, reviewer, note)`

按是否存在待审更新分支：

- **approve**
  - 若 `has_pending_update`：把 `pending_*` 拷入线上 `version/install_url/archive_hash`，
    清空 `pending_*`、`has_pending_update=FALSE`，`status` 保持 `approved`，记录审计字段。
  - 否则：首次审核 `pending → approved`。
  - 发 `SKILL_APPROVED` 事件，data 含 `publisher`、`note`、`is_update`。
- **reject**
  - 若 `has_pending_update`：**丢弃 `pending_*`、保留线上已通过版本**（`status` 仍
    `approved`），清 `has_pending_update`，记录 `review_note`。
  - 否则：首次审核 `pending → rejected`。
  - 发 `SKILL_REJECTED` 事件，data 含 `publisher`、`note`、`is_update`。

`is_update = has_pending_update`（在分支前读取），供通知文案区分「首发审核」与「版本更新审核」。

## 审核通知

### 事件

在 `xiaopaw/event_bus.py` 的 `CommunityEvent` 新增：

```python
SKILL_REJECTED = "community.skill_rejected"
```

`moderate_skill` 的 reject 分支改发 `SKILL_REJECTED`（此前发 `SKILL_SUSPENDED`）。
`SKILL_SUSPENDED` 保留给 `withdraw_skill`（发布者主动下架）。

### `NotificationStore`（`xiaopaw/notifications/store.py`，新建）

纯 PG CRUD（psycopg2，连接模式参照 `CommunityRegistry`）：

- `create(recipient, type, title, body="", payload=None) -> dict`
- `list(recipient, unread_only=False, page=1, page_size=20) -> {"notifications": [...], "total": int}`
- `unread_count(recipient) -> int`
- `mark_read(notification_id, recipient) -> bool`（带 recipient 条件，防越权改他人通知）
- `mark_all_read(recipient) -> int`

所有方法 DB 异常降级（记 warning + 返回空/False/0），与现有 registry 风格一致。

### `NotificationService`（同文件 `xiaopaw/notifications/store.py` 或 `service.py`，新建）

EventBus 同步 handler（与 `ActivityRecorder.handle_event` 同模式）：

- `handle_event(payload)`：仅处理 `CommunityEvent.SKILL_APPROVED` / `SKILL_REJECTED`，其他忽略。
- 从 `payload.data` 取 `skill_name`、`publisher`、`note`、`is_update`。
- 缺 `publisher` 时忽略（不落地）。
- 依 type 生成中文标题/正文，调用 `store.create(recipient=publisher, ...)`。
- store 异常被吞（记 warning），不影响 EventBus 其他订阅者。

### 装配（`main.py` / `server.py`）

- `main.py`：当 `pg_store`（即 `cfg.memory.db_dsn`）可用时，创建
  `NotificationStore(dsn=cfg.memory.db_dsn)` 与 `NotificationService(store)`，
  `event_bus.subscribe(CommunityEvent.SKILL_APPROVED, svc.handle_event)` 及 `SKILL_REJECTED`。
- 经 `create_frontend_app(... notification_store=...)` 注入 `app["notification_store"]`。
- `server.py` 增加 `notification_store` 参数与 `app[...]` 赋值，并注册通知路由。

### 路由（`xiaopaw/frontend/routes/notifications.py`，新建）

复用 `helpers` 的 `check_auth` / `get_current_user`；recipient **强制**取当前登录用户的
username，忽略任何客户端传入的 recipient。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/frontend/notifications` | 分页列表，`?unread_only=&page=&page_size=` |
| GET | `/api/frontend/notifications/unread-count` | `{"count": n}` |
| POST | `/api/frontend/notifications/{id}/read` | 标记单条已读 |
| POST | `/api/frontend/notifications/read-all` | 全部已读 |

未登录返回 401；`notification_store` 未装配返回 503。`{id}/read` 命中他人通知（recipient
不匹配）返回 404。路由在 `routes/__init__.py` 注册。

## 测试

### 纯逻辑（无 PG，必跑）

- `tests/unit/test_notification_service.py`：`NotificationService.handle_event`
  - `SKILL_APPROVED` → `store.create` 以 recipient=publisher、type=`skill_approved` 调用一次。
  - `SKILL_REJECTED` → type=`skill_rejected`，payload 含 note/is_update。
  - 缺 publisher → 不调用 store。
  - 非社区事件 / 其他 CommunityEvent → 忽略。
  - store 抛异常 → 被吞，不抛出。
- `tests/integration/test_notifications_api.py`：MagicMock store（仿 `test_skill_moderation.py`
  的 `admin_app` 模式），真实 `UserAuth`。
  - 未登录 401；store 未装配 503。
  - list / unread-count / read / read-all 各自 recipient 强制为当前用户。
  - 越权标记他人通知（store 返回 False）→ 404。

### PG 依赖（本机 skip，仿 `pg_registry` fixture）

- `tests/integration/test_skill_update_moderation.py`：完整闭环
  - publish → approve（发布者收到 approved 通知，若挂载 service）→
  - update 产物字段 → 线上不变、`has_pending_update=TRUE`、`list_pending` 出现 →
  - approve 更新 → 线上切到新 version/install_url/hash、`has_pending_update=FALSE` →
  - 再 update → reject 更新 → 线上保留上一个已通过版本、status 仍 approved。
  - 展示字段更新 → 立即生效、不进 pending。

## 影响面 / 兼容性

- 新增列均有默认值，旧数据 `has_pending_update=FALSE`，行为向后兼容。
- `list_skills`/`install_skill` 仍读线上字段，语义不变。
- reject 事件由 `SKILL_SUSPENDED` 改为 `SKILL_REJECTED`：`ActivityRecorder` 只认
  `AgentEvent`，不受影响；无其他 `SKILL_SUSPENDED` 订阅者。

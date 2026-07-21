# 多租户隔离基础（Spec A） — 设计方案

- 日期：2026-07-14
- 状态：已实现（SQLite 测试 20 passed / PG 测试 skip-gated）
- 关联：`docs/system-architecture.md` 演进路线「多租户隔离、技能计费与分成」
- 定位：本 spec 是「多租户隔离、技能计费与分成」大任务拆分后的 **第一块（地基）**，
  是后续 Spec B（技能定价 + 购买/授权）、Spec C（分成与结算 + 支付网关）的前置。

## 背景与问题

玄机当前是单用户导向的个人助手，无任何租户/组织概念：

- 归属仅靠 `routing_key = p2p:web_{username}`（用户名全局唯一），私有数据（`memories` /
  `conversations` / `sessions` / `agent_activities`）按 routing_key 隔离。
- `auth.db` 有 `users` / `teams` / `team_members` / `team_invitations`，但 team 之上无组织层。
- 平台仅一个 bootstrap `admin`（`is_admin` 全局，用于全局市场审核）。
- 会话共享（team 维度）会跨 routing_key 访问，是**唯一的跨用户访问面**。

要支撑未来的组织级计费与分成，需要先建立**组织（租户）边界**并在数据面做隔离。

## 目标

- 引入「组织」作为租户边界（高于 team）：`组织 → 团队 → 用户`。
- 私有数据按用户隔离（复用 routing_key）；在唯一的跨用户越权面（会话共享）做 org 纵深防御。
- 现有单用户数据平滑迁移到「默认组织」，零感知升级。

## 非目标（YAGNI）

- 不做组织创建/管理 UI 与完整 org CRUD（留待后续 spec，本 spec 仅只读展示当前组织）。
- 不做计费/分成（Spec B/C）。
- 不给 `memories` / `conversations` / `agent_activities` 加 org_id（严格按用户、从不共享，
  routing_key 隔离已 ⊆ 按 org 隔离）。
- 不做 PostgreSQL RLS。
- 市场（`community_skills`）保持全局公共，不加 org_id。

## 关键决策（已与用户确认）

| 决策点 | 选择 |
| --- | --- |
| 推进方式 | 先做多租户隔离基础（Spec A），B/C 后续 |
| 租户粒度 | 租户 = 组织（高于 team） |
| 用户↔组织 | 一人属一组织（users.org_id 直存，O(1) 取用） |
| 市场隔离 | 全局公共（community_skills 不加 org_id） |
| 组织创建/迁移 | 默认组织 + 迁移；新注册用户默认加入默认组织 |
| 隔离机制 | ② 地基 + 仅 sessions 加 org_id 做纵深防御（非 RLS） |
| 管理模型 | org 设 owner；org owner 管理本 org 成员；平台 is_admin 维持全局，不新增 org-admin 角色 |

## 数据模型

### auth.db（SQLite）

新表：

```sql
CREATE TABLE IF NOT EXISTS organizations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    owner_id   INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
```

幂等迁移（沿用现有 `is_admin` 的 `PRAGMA table_info(...)` 检测模式，SQLite 无法对非空表
`ADD COLUMN NOT NULL`，故加为可空列后回填）：

- `users` 增 `org_id INTEGER`（引用 organizations(id)）
- `teams` 增 `org_id INTEGER`（引用 organizations(id)）

### PG（schema.sql）

```sql
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS org_id BIGINT;
CREATE INDEX IF NOT EXISTS idx_sessions_org_id ON sessions (org_id);
```

`community_skills`、`memories`、`conversations`、`agent_activities` 均不变。

## 启动引导与迁移

`UserAuth.__init__` 调用顺序调整为：

1. `_init_db()` — 建表 + 上述幂等列迁移
2. `_init_default_admin()` — 无用户时建默认 admin（既有逻辑）
3. `_init_default_org()`（新增） — 若 `organizations` 为空，创建「默认组织」，owner = 首个用户
   （即 admin）
4. `_backfill_org_ids()`（新增） — 将 `users` / `teams` 中 `org_id IS NULL` 的行回填为默认组织 id

`register()`：新用户 `org_id` 设为默认组织 id。

> 幂等性：以上均可重复执行（`IF NOT EXISTS` / 空表判断 / 仅回填 NULL），旧库升级安全。

## auth 层改动

### UserAuth

- `get_user(user_id)` 返回值新增 `org_id`
- 新增 `get_default_org_id() -> int | None`
- 新增 `get_org(org_id) -> dict | None`
- 新增 `create_organization(name, owner_id) -> dict`
- 新增 `set_user_org(user_id, org_id) -> bool`
- 新增 `all_username_org_map() -> dict[str, int]`（供启动回填 sessions.org_id，返回
  `{username: org_id}`）

### TeamStore

- `create_team(name, description, owner_id, org_id)` — 落 `teams.org_id`；调用方默认取 owner 的 org_id
- `add_member(team_id, user_id, role)` — 校验 `加入者 org_id == team.org_id`，跨组织抛
  `ValueError("跨组织禁止加入团队")`
- 邀请加入路径（`use_invitation` / join）同样校验同 org
- `get_team(team_id)` 返回值新增 `org_id`
- 新增 `get_team_org_id(team_id) -> int | None`

## sessions.org_id 打通与强制

### 写入

- `PGStore.save_session(...)` 增参数 `org_id: int | None = None`，写入 INSERT 列；
  `ON CONFLICT (id) DO UPDATE` 分支保持不覆盖既有 org_id（仅在为 NULL 时补写，避免误改）。
- `handle_message`（`session.py`，`save_session` 唯一调用点）传入 `org_id=user.get("org_id")`。

### 启动回填

- `main.py` 装配阶段：用 `user_auth.all_username_org_map()` 构造 `{routing_key: org_id}`
  （routing_key = `p2p:web_{username}`），调用新增的
  `PGStore.backfill_session_org_ids(routing_key_to_org: dict[str, int]) -> int`
  执行 `UPDATE sessions SET org_id = %s WHERE routing_key = %s AND org_id IS NULL`。
  PG 不可用时静默降级。

### 纵深防御（session.py）

- 在上个任务已落地的 `_resolve_shared_session_permission(request, session_id)` 中追加：
  解析到的会话记录其 `org_id` 必须等于当前用户 `org_id`，否则视为不可见（返回 None →
  上层 404）。org_id 为 NULL（历史未回填）时按当前用户 org 放行（兼容），不阻断。
- 会话共享 handler（`team.py`）：分享时把 `sessions.org_id` 设为分享者 org_id，并校验目标
  team 的 org_id == 分享者 org_id（结构上单 org 用户已保证，此为 belt-and-suspenders）。

## 边界强制链路

```
团队创建/加入 → 限定单 org（auth 层，跨 org 拒绝）
      ↓
会话共享 → 仅同 org team（team.py handler + 写入 sessions.org_id）
      ↓
共享会话读写解析 → 再验 org_id 匹配（session.py 纵深防御）
```

- 市场（community_skills）：全局公共，不变。
- 平台 `is_admin`：仅全局市场审核，不变。
- org owner：管理本 org 成员（完整 org 管理 API 留待后续 spec）。

## 本 spec API

仅新增一个只读端点，供前端展示当前组织信息：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/frontend/org` | 返回当前登录用户所属组织 `{id, name, owner_id, created_at}` |

未登录 401；用户无 org（异常态）返回 404。路由复用 helpers 的 `check_auth`/`get_current_user`，
org 由 `user["org_id"]` 解析，忽略任何客户端传参。

## 测试

### 纯 SQLite（无 PG，必跑）

`tests/integration/test_multitenant_isolation.py`：

- 默认组织 bootstrap：初始化后存在「默认组织」，admin 的 `org_id` 指向它。
- 新注册用户 `org_id` = 默认组织。
- legacy 迁移：预置无 `org_id` 的 users/teams（裸 sqlite 建表 + 插入），`UserAuth`/`TeamStore`
  初始化后 org_id 被回填为默认组织。
- `TeamStore.create_team` 落 `org_id`；`get_team` 含 org_id。
- `add_member` 跨组织（加入者 org_id != team.org_id）抛 `ValueError`；同 org 正常。

### session 隔离（无 PG，复用 `test_session_share_permission.py` 的 fake 模式）

- 扩展/新增：`_resolve_shared_session_permission` 在会话 org_id 与当前用户 org_id 不匹配时
  返回 None（→ 上层 404）；匹配时按 share_permission 正常返回。
- org_id 为 NULL 时兼容放行（不因历史数据阻断）。

### PG 依赖（本机 skip，仿 `pg_registry` fixture）

- `save_session` 落 `org_id`；`ON CONFLICT` 不覆盖既有非空 org_id。
- `backfill_session_org_ids` 仅更新 `org_id IS NULL` 的行，返回更新计数。

## 影响面 / 兼容性

- auth.db 新增列均可空并回填，旧库升级安全、幂等。
- `sessions.org_id` 可空，历史行由启动回填补齐；读路径对 NULL 兼容放行。
- routing_key、市场、memory 检索语义均不变。
- 单用户部署：所有数据归属唯一「默认组织」，行为与升级前一致。

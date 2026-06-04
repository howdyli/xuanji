# 技能列表管理（Skill Manager）设计

- **日期**: 2026-05-29
- **作者**: Howdy + Qoder
- **状态**: Approved (待实现)
- **关联**: `xiaopaw/skills_mgmt/`、`frontend/src/components/SkillsPanel.tsx`、参考截图见 brainstorming 会话

## 1. 背景

WorkBuddy 当前已有技能管理面板 [SkillsPanel](../../../frontend/src/components/SkillsPanel.tsx)，采用左右分栏布局，能列出 builtin/user 技能、启停、上传 ZIP、创建。但用户期望一个对标主流 AI Agent 平台（Cursor / ClawHub）的更生态化界面：

- 网格卡片视觉、双 Tab（**技能市场 / 已安装**），承接"发现 + 安装 + 管理"全链路
- 引入"技能市场"概念，从远程仓库（Vercel Skills、ClawHub）实时获取可安装技能并支持一键安装
- 视觉延续 WorkBuddy 风格（浅色、圆角、轻阴影）

## 2. 目标 / 非目标

### Goals
1. 按截图重构「技能」一级页面为 Header + Tabs + 4 列响应式卡片网格
2. 后端引入 `skill_market` 持久化表与定时同步任务，把 Vercel Skills 与 ClawHub 索引落到本地
3. 一键安装：用户在市场卡片点击安装 → 后端下载 ZIP → 解压到 `user_skills/` → 自动出现在「已安装」Tab
4. 三入口添加：从市场安装 / 上传 ZIP / 手动创建 SKILL.md，一个统一入口承载

### Non-Goals
- 不实现"技能评分 / 评论 / 收藏"等社区功能（YAGNI）
- 不实现技能签名校验、CDN 镜像等增强（留作未来）
- 不重写 [SessionSkillsPicker](../../../frontend/src/components/SessionSkillsPicker.tsx)（聊天底部浮层选择器，独立用途）
- 不引入新的状态管理库（继续用 useState/useCallback）

## 3. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                  Frontend (React + Tailwind)                │
│                                                             │
│  SkillManagerView                                           │
│   ├── Header (title + search + "+ 添加技能")                  │
│   ├── Tabs (技能市场 | 已安装 N)                              │
│   ├── Grid (4-col responsive)                               │
│   │    └── SkillCard × N                                    │
│   ├── SkillDetailDrawer (右抽屉)                              │
│   ├── AddSkillMenu  (三入口面板)                              │
│   ├── CreateSkillDialog                                     │
│   └── UploadSkillDialog                                     │
└────────────────┬────────────────────┬───────────────────────┘
                 │ /api/frontend       │ /api/frontend/market
                 ▼                     ▼
┌────────────────────────────┐  ┌─────────────────────────────┐
│ skills_mgmt/api.py         │  │ skills_mgmt/api.py (扩展)    │
│  list / detail / toggle    │  │  GET  /market/skills        │
│  upload / create / delete  │  │  POST /market/skills/{n}/install│
│  download                  │  │  POST /market/refresh       │
└────────────────────────────┘  └────────────┬────────────────┘
                                             │
                              ┌──────────────┴───────────────┐
                              │ skills_mgmt/market.py (新增) │
                              │  MarketSync                  │
                              │  MarketRegistry              │
                              └──────┬─────────────┬─────────┘
                                     │             │
                              ┌──────▼─────┐  ┌────▼────────────┐
                              │ skill_market│  │ Vercel Skills + │
                              │   (Postgres)│  │ ClawHub HTTPS   │
                              └─────────────┘  └─────────────────┘
                                     ▲
                                     │ 6h cron
                              ┌──────┴──────┐
                              │ cron/service│
                              └─────────────┘
```

## 4. 数据模型

### 4.1 PostgreSQL 新增表 `skill_market`

```sql
CREATE TABLE IF NOT EXISTS skill_market (
  name           TEXT PRIMARY KEY,
  source_type    TEXT NOT NULL CHECK (source_type IN ('vercel', 'clawhub')),
  version        TEXT,
  description    TEXT,
  author         TEXT,
  repo_url       TEXT,
  install_url    TEXT NOT NULL,    -- ZIP / git tarball
  manifest_json  JSONB NOT NULL,   -- 原始 manifest 完整快照
  updated_at     TIMESTAMPTZ,      -- 远端 release 时间
  fetched_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skill_market_source ON skill_market(source_type);
CREATE INDEX IF NOT EXISTS idx_skill_market_fetched ON skill_market(fetched_at);
```

### 4.2 既有 `skills` 表 / `SkillInfo` 不动

仅在 `SkillInfo.to_dict()` 中**派生**一个字段：

```python
{
  ...,
  "is_bundle": <type=='task' 且 files 含 .py/.sh/.js/.ts>,
}
```

首字母图标由前端从 `name[0].toUpperCase()` 取，颜色由前端 hash(name) → 紫/蓝/绿/橙四档。SKILL.md frontmatter 不引入新字段。

### 4.3 市场实体 `MarketEntry`

```python
@dataclass
class MarketEntry:
    name: str
    source_type: str           # 'vercel' | 'clawhub'
    version: str
    description: str
    author: str
    repo_url: str
    install_url: str
    manifest_json: dict
    updated_at: datetime | None
    fetched_at: datetime

    def to_dict(self, *, installed: bool) -> dict: ...
```

## 5. 后端变更

### 5.1 新增 `xiaopaw/skills_mgmt/market.py`

**配置**：在 `config.yaml` 新增段：

```yaml
skill_market:
  vercel_index_url: "https://raw.githubusercontent.com/vercel/skills/main/index.json"
  clawhub_index_url: "https://clawhub.example.com/api/skills/index"
  sync_interval_hours: 6
  fetch_timeout_seconds: 60
  enabled: true
```

实际 URL 在实现阶段确认；若上游协议未确定，URL 为占位、可在 dev 环境通过环境变量覆盖。

```python
class MarketSync:
    """从 Vercel Skills + ClawHub 拉取索引并落库。

    成功率：单源失败不阻断另一源；记录每源最后同步状态到 metrics。
    """
    def __init__(self, db_pool, http_client, vercel_index_url, clawhub_index_url): ...
    async def sync_to_db(self) -> SyncResult:
        """全量同步两源；幂等（基于 name PK upsert）。"""
    async def _fetch_vercel(self) -> list[MarketEntry]: ...
    async def _fetch_clawhub(self) -> list[MarketEntry]: ...

class MarketRegistry:
    """读取 + 安装。"""
    def __init__(self, db_pool, skill_registry: SkillRegistry, http_client): ...
    async def list_market(self, *, search: str | None = None) -> list[MarketEntry]: ...
    async def get_market(self, name: str) -> MarketEntry | None: ...
    async def install(self, name: str) -> InstallResult:
        """下载 install_url → 校验大小 → unpack_skill → registry.sync_to_db。"""
```

**安装流程**：
1. 取 `install_url`
2. HTTPS GET 下载到内存（≤ `DEFAULT_MAX_ARCHIVE_BYTES`）
3. 复用现有 `xiaopaw.skills_mgmt.packager.unpack_skill(archive_bytes, target_root=registry.user_dir, overwrite=False)`
4. 调 `skill_registry.sync_to_db()`
5. 返回 `{ok, name, files}`

### 5.2 cron 注册

在 `xiaopaw/cron/service.py` 启动时增加一项：

- 启动后立即跑一次 `MarketSync.sync_to_db()`（异步，不阻塞 startup）
- 之后每 6 小时跑一次

### 5.3 `xiaopaw/skills_mgmt/api.py` 新增 endpoint

```
GET   /api/frontend/market/skills              → list_market（每条带 installed 标志）
GET   /api/frontend/market/skills/{name}       → get_market 详情
POST  /api/frontend/market/skills/{name}/install → 一键安装
POST  /api/frontend/market/refresh             → 立即触发 MarketSync.sync_to_db
```

`/market/skills` 响应需在每条上拼 `installed: bool`（与本地 SkillRegistry 名称比对）。

### 5.4 `SkillInfo.to_dict()` 派生字段

```python
SCRIPT_EXTS = (".py", ".sh", ".js", ".ts")

def to_dict(self):
    return {
        ...,
        "is_bundle": self.type == "task" and any(
            f.endswith(SCRIPT_EXTS) for f in self.files
        ),
    }
```

## 6. 前端变更

### 6.1 新组件目录 `frontend/src/components/skills/`

| 文件 | 责任 |
|------|------|
| `SkillManagerView.tsx` | 主视图：Header + Tabs + Grid + 抽屉调度 |
| `SkillCard.tsx` | 单卡片：圆形首字母图标 + 名称 + 套件标签 + `…` |
| `SkillDetailDrawer.tsx` | 右侧抽屉：SKILL.md 渲染 + 启停开关 + 卸载/导出 |
| `AddSkillMenu.tsx` | 三入口下拉（市场 / 上传 ZIP / 手动创建） |
| `CreateSkillDialog.tsx` | 手动创建表单（迁自旧 SkillsPanel） |
| `UploadSkillDialog.tsx` | 上传 ZIP（迁自旧 SkillsPanel） |
| `MarketRefreshButton.tsx` | 「上次同步 X 分钟前」+ 立即刷新 |
| `useSkills.ts` | 自定义 hook：列表 + CRUD + 安装的 fetch 封装 |

### 6.2 路由切换

`frontend/src/App.tsx` 中 `activeNav==='skill'` 改为渲染 `SkillManagerView`，删除 [SkillsPanel](../../../frontend/src/components/SkillsPanel.tsx)（其内的 create/upload 逻辑迁出后整体下线）。

### 6.3 视觉规则（呼应截图）

- 容器：`max-w-7xl mx-auto px-8 py-6`
- 卡片：`bg-white rounded-2xl border border-zinc-200 hover:shadow-md transition p-5 relative`
- 圆形图标：`w-10 h-10 rounded-full flex items-center justify-center text-white font-medium`，按 `name` hash 取色（紫/蓝/绿/橙四档）
- 「套件」标签：`bg-violet-100 text-violet-700 px-2 py-0.5 rounded text-xs font-medium`
- 描述：`text-sm text-zinc-600 line-clamp-2 mt-3`
- 已禁用：卡片整体 `opacity-60` + 右上角灰色「已禁用」角标
- 市场已安装：安装按钮变为「已安装」灰态 disabled

### 6.4 关键交互

- 搜索框：仅过滤当前 Tab；空字符串显示全部；按 name + description 模糊匹配
- Tab 切换：保留各自 search 状态（独立 state）
- 卡片点击：打开右抽屉；`…` 菜单当前仅"查看详情"（点击= 等价于点卡片）
- 详情抽屉内部按钮：启用/禁用、卸载（仅 user）、导出 ZIP
- 添加技能 → 三入口面板（小弹层）：
  1. **从市场安装**：切到「市场」Tab，焦点搜索框
  2. **上传 ZIP**：弹出 UploadSkillDialog
  3. **手动创建**：弹出 CreateSkillDialog
- 市场卡片点击「安装」按钮：调 `/market/skills/{name}/install`，成功后 toast + 刷新两 Tab 数据；失败显示错误码到 toast

## 7. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Vercel/ClawHub manifest 协议变化 | 同步失败 | `manifest_json` 存原始快照；source-specific adapter 隔离差异 |
| cron 失败 / 首次启动远端不可达 | 市场长期空白 | UI 显示「上次同步：N 分钟前」+「立即刷新」按钮；fetched_at 为空时 Tab 显示空态指引 |
| 远端 ZIP 体积 / 恶意 | 写爆磁盘 / RCE | 复用现有 `DEFAULT_MAX_ARCHIVE_BYTES` 上限；`unpack_skill` 已有路径穿越校验 |
| 沙盒环境下 install 写不动 user_skills | 安装报错 | 与之前 SQLite 错误同源；启动指南要求服务以 IDE 外的 shell 运行 |
| 单源失败拖慢同步 | 同步耗时长 | `_fetch_vercel` 与 `_fetch_clawhub` 并发；单源 timeout 60s 后跳过并记录 |
| 重命名冲突（市场技能 name 与本地 user 同名） | 安装失败 | install 默认 `overwrite=False` 返 409；前端引导用户手动卸载旧版本后重试 |
| 用户高频点「立即刷新」 | 远端限流 / 重复任务堆叠 | 前端按钮 30s 内 disabled；后端 sync_to_db 加进程内 asyncio.Lock，重复请求合并到正在跑的任务 |
| 上游 manifest URL 尚未敲定 | 实现卡顿 | 配置项允许 dev 环境通过 env 覆盖；CI/CD 用 fixture JSON 静态文件验证 |

## 8. 实现顺序

每步独立可测，且任意一步停下页面仍可用（旧 SkillsPanel 在 5 之前保持可见）。

1. **后端：market 表迁移 + Vercel adapter**——能跑出 `MarketSync._fetch_vercel()` 单测
2. **后端：MarketRegistry.install()**——复用 unpack_skill；提供 `/market/skills/{n}/install`
3. **后端：ClawHub adapter + cron 注册 + `/market/refresh`**
4. **前端：`SkillManagerView` 骨架 + Tabs + Grid（先 mock 数据）**——与 App.tsx 路由打通但保留旧 SkillsPanel 兜底
5. **前端：接「已安装」API（list/detail/toggle/delete/upload/create）+ 抽屉 + 三入口**——切换至新视图，下线旧 SkillsPanel
6. **前端：接「市场」API + 安装按钮 + MarketRefreshButton**
7. **联调 + 视觉打磨 + e2e 测试**

## 9. 测试要点

- **单元**：`MarketSync._fetch_vercel/_fetch_clawhub` 用 fixture JSON；`MarketRegistry.install` mock http 下载流
- **集成**：cron 注册 + DB upsert 幂等；安装→list 显示 installed=true
- **e2e**：复用 `tests/e2e` 套路，新增 `test_e2e_skill_manager.py`：① 浏览器打开技能页 ② 切到市场 Tab 看到至少一条 ③ 一键安装某技能 ④ 切回已安装 Tab 验证存在
- **沙盒**：现有 sandbox_guard 不影响纯 HTTP fetch + 解压；如有 e2e 报 sandbox 拦截，重启服务于 IDE 外 shell

## 10. Out of Scope（未来）

- 技能签名校验、CDN 镜像、增量更新（diff 安装）
- 用户自定义订阅仓库 URL（当前仅官方两源）
- 技能评分、评论、使用统计
- 技能依赖关系（一个套件依赖另一个套件）
- 卡片菜单的「编辑」「禁用」「卸载」直接入口（当前仅"查看详情"，其余从抽屉操作）

## 11. 决策记录

| 决策 | 选项 | 选定 | 理由 |
|------|------|------|------|
| 范围 | UI重构 / +套件标签 / 完整含市场后端 | **完整含市场** | 用户对标 Cursor 等生态平台 |
| 市场源 | Vercel+ClawHub / 内置manifest / 用户订阅 | **Vercel+ClawHub** | 已有 find-skills 能力可借鉴；社区生态 |
| 套件语义 | 可执行脚本 / bundle列表 / 发布包 | **可执行脚本派生** | 不引新字段，零 SKILL.md 迁移成本 |
| 添加入口 | 三入口 / 仅市场 / 直接创建表单 | **三入口** | 覆盖发现/分享/自定义全场景 |
| 卡片菜单 | 多操作 / 仅详情 | **仅详情** | 简化卡片表面，操作下沉至抽屉 |
| 索引刷新 | 按需+缓存 / cron同步DB / 前端直拉 | **cron同步DB** | 首屏体验稳定，便于审计 |

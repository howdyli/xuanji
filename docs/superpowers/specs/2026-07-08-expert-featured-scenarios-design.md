# 精选场景（Featured Scenarios）设计文档 / PRD

- 日期：2026-07-08
- 状态：已评审（用户确认「符合预期」）
- 作者：玄机 XiaoPaw v2 团队
- 关联模块：专家（Expert）发现页

## 1. 背景与目标

项目已存在完整的专家模块：

- 后端 `xiaopaw/frontend/expert.py`（`ExpertRegistry`，SQLite 存储、8 个内置专家团、CRUD、分类）
- 后端 `xiaopaw/frontend/routes/expert.py`（专家 REST API）
- 前端 `frontend/src/components/ExpertManagerView.tsx`（分类标签 + 卡片网格 + 搜索 + 详情抽屉 + 新建/编辑/删除 + 「召唤」选中）

参考 WorkBuddy 的「专家·技能·连接器」页面，本次目标是**在现有专家发现页上补齐「精选场景」这一发现/运营层能力**：在页面顶部提供一组横向可滚动的场景卡片，每个场景（如「内容创作」「投资分析」）聚合最多 3 个推荐专家，帮助用户按使用场景快速找到并进入合适的专家。

本次为**增强**，不重写现有页面，不改动现有专家 CRUD 与选中逻辑。

## 2. 范围

### 2.1 本次包含

- 后端新增「场景」数据模型与只读查询接口。
- 前端在 `ExpertManagerView` 顶部新增「精选场景」区块（横向滚动卡片轨道）。
- 场景卡采用主题渐变背景 + 图标（沿用天蓝系配色，无图片资产）。
- 点击场景卡内的专家 → 复用现有详情抽屉 `DetailDrawer`。

### 2.2 明确不做（YAGNI）

- 专家 / 专家团 分栏。
- 综合 / 最热 / 最新 排序。
- 我的专家（收藏）。
- 顶部三分类导航（专家 / 技能 / 连接器）。
- 场景后台 CRUD 管理界面。
- 真实图片素材（场景配图）。

## 3. 用户故事与验收标准

### US-1：浏览精选场景
> 作为用户，我进入专家页时能在顶部看到一排「精选场景」卡片，快速了解平台按场景组织的专家。

验收：
- 专家页顶部（分类标签栏上方）展示「精选场景」区块，含标题与横向卡片轨道。
- 每张场景卡显示：主题渐变头图（图标 + 标题 + 副标题）+ 下方最多 3 个推荐专家（小头像 + 名字）。
- 卡片数量超出视口宽度时可横向滚动，右侧有渐隐提示与右箭头翻页控件。

### US-2：从场景进入专家详情
> 作为用户，我点击场景卡里的某个专家，能直接查看该专家详情并可召唤。

验收：
- 点击场景卡内任一专家，打开现有 `DetailDrawer`，可查看 / 编辑 / 召唤。
- 交互与现有专家网格卡片点击一致，不新增独立交互面。

### US-3：渐进增强不阻塞
> 作为用户，即使精选场景数据缺失或加载失败，我仍能正常使用下方专家列表。

验收：
- 场景接口加载中：场景区显示独立 skeleton；下方专家网格独立加载。
- 场景接口失败或返回空：**整个场景区隐藏**，不影响专家网格与页面其余功能，控制台无未捕获错误。
- 场景引用了已删除 / 不存在的专家：后端自动过滤；某场景可展示少于 3 个专家，仍正常渲染。

## 4. 数据模型

新增表 `expert_scenarios`，与 `ExpertRegistry` 同库（`auth.db`）同风格（`WAL`、`_init_defaults` 注入内置数据）。

| 字段 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | 自增主键 |
| `key` | TEXT | UNIQUE NOT NULL | 场景标识，如 `content_create` |
| `title` | TEXT | NOT NULL | 场景名（内容创作 / 投资分析…） |
| `subtitle` | TEXT | NOT NULL DEFAULT '' | 一句话描述，可空 |
| `icon` | TEXT | NOT NULL DEFAULT 'expert' | 图标键，复用前端 `ICON_EMOJIS` 体系 |
| `gradient` | TEXT | NOT NULL DEFAULT 'sky' | 渐变主题键（`sky`/`violet`/…），前端映射为天蓝系渐变 |
| `expert_names` | TEXT | NOT NULL DEFAULT '[]' | 关联专家 `name` 的 JSON 数组，有序，展示取前 3 |
| `sort_order` | INTEGER | NOT NULL DEFAULT 0 | 排序权重，升序 |
| `created_at` | TEXT | NOT NULL | ISO8601 |
| `updated_at` | TEXT | NOT NULL | ISO8601 |

### 4.1 内置默认场景（5 个，对齐参考截图）

按 `sort_order` 升序，`expert_names` **只引用现有 8 个内置专家的 `name`**（`dev_team` / `trading_team` / `content_team` / `ip_partner` / `research_team` / `cloud_support` / `opc_team` / `stock_research`），确保每个默认场景过滤后至少有 1 个有效专家：

1. `content_create` — 内容创作（icon `content`, gradient `pink`）→ `content_team`, `research_team`
2. `invest_analysis` — 投资分析（icon `trading`, gradient `amber`）→ `trading_team`, `stock_research`
3. `deep_research` — 深度研究（icon `research`, gradient `violet`）→ `research_team`, `content_team`
4. `small_business` — 一人公司 / 小微企业（icon `opc`, gradient `orange`）→ `opc_team`, `ip_partner`
5. `tech_delivery` — 技术交付（icon `dev`, gradient `sky`）→ `dev_team`, `cloud_support`

> 说明：本次默认场景不照搬参考截图里项目暂无对应专家的场景（如法律咨询 / 电商运营），改用与现有内置专家匹配的 5 个场景，避免出现空场景；后续新增专家后可再扩充场景与映射。渐变键统一映射到以 `#3898EC` 为基调的天蓝系配色，与侧边栏/登录页视觉规范一致。

## 5. 后端 API

新增 `xiaopaw/frontend/routes/scenario.py`，鉴权复用 `check_auth`。

### `GET /api/frontend/expert-scenarios`

- 鉴权：需登录，未登录返回 `401`。
- 行为：返回场景列表（按 `sort_order` 升序）。每个场景**内联展开**其前 3 个有效专家的精简信息，前端一次取全、无需二次请求。
- 专家精简字段：`name`、`display_name`、`icon`、`team`。
- 引用了不存在专家的槽位被过滤，仅返回有效专家。

响应示例：

```json
{
  "scenarios": [
    {
      "key": "content_create",
      "title": "内容创作",
      "subtitle": "从创意到成品的多模态内容生产",
      "icon": "content",
      "gradient": "pink",
      "experts": [
        { "name": "content_team", "display_name": "内容创作专家团", "icon": "content", "team": "玄机团队" }
      ]
    }
  ]
}
```

- 若 `scenario_registry` 未初始化：返回 `{"scenarios": []}`（与现有 experts 路由的降级方式一致）。
- 本次仅提供只读查询接口，不提供场景的增删改。

### 注册

在现有路由注册处（与 `register_expert_routes` 同级）新增 `register_scenario_routes(app)`，并在应用启动时初始化 `scenario_registry`（与 `expert_registry` 一致的装配方式，指向同一 `auth.db`）。

## 6. 前端设计

增强 `frontend/src/components/ExpertManagerView.tsx`，不新开页面、不改动现有专家网格与 CRUD。

### 6.1 布局

- 在**分类标签栏上方**插入「精选场景」区块：区块标题 + 横向可滚动卡片轨道。
- 轨道右侧渐隐遮罩 + 右箭头翻页按钮（对齐 WorkBuddy 截图交互）。

### 6.2 场景卡

- 头部：主题渐变背景（由 `gradient` 键映射，天蓝系为主）+ 图标（`ICON_EMOJIS[icon]`）+ 标题 + 副标题。
- 主体：最多 3 行推荐专家，每行小头像（复用 `gradientOf(name)` + `ICON_EMOJIS[expert.icon]`）+ `display_name`。
- 复用现有 `ICON_EMOJIS`、`gradientOf` 等工具，保持视觉一致。

### 6.3 交互

- 点击场景卡内任一专家 → 复用现有 `DetailDrawer`（查看 / 编辑 / 召唤），行为与网格卡点击一致。

### 6.4 状态与降级

- 加载中：场景区独立 skeleton（不阻塞专家网格加载）。
- 接口失败或空数组：整个场景区隐藏，专家网格与页面其余功能照常。
- 响应式：窄屏下卡片宽度收缩，保持横向滚动。

### 6.5 数据获取

- 新增 `GET /api/frontend/expert-scenarios` 拉取，使用现有 `apiFetch`。
- 场景内专家信息由接口内联返回，前端无需额外按名查询。

## 7. 错误处理与边界

- 后端接口异常 → 前端 `catch` 后隐藏场景区，专家网格正常。
- `expert_names` 引用失效 → 后端过滤，某场景可少于 3 个专家，前端正常渲染。
- 某场景过滤后**无任何有效专家** → 该场景从接口返回中省略，不下发空场景。
- 所有场景均无效（返回空数组）→ 前端场景区整体不渲染。

## 8. 测试计划

- 后端单测（沿用现有 registry 测试风格）：
  - `expert_scenarios` 建表与内置默认注入。
  - 幂等：重复初始化不重复插入。
  - 专家引用过滤：引用不存在专家时，接口层过滤，仅返回有效专家；截取前 3。
- 接口集成测试：
  - `GET /api/frontend/expert-scenarios` 未登录返回 `401`。
  - 已登录返回结构正确（含内联 `experts` 精简字段、按 `sort_order` 升序）。
- 前端：
  - `npx tsc --noEmit -p tsconfig.app.json` 通过。
  - Playwright 视觉验证：场景区正常渲染、横向滚动、点击专家弹出详情抽屉；控制台 0 error；接口失败时场景区隐藏、页面可用。

## 9. 实现影响清单（预计）

- 新增：`xiaopaw/frontend/routes/scenario.py`（场景查询路由）。
- 新增：场景 Registry（可置于 `xiaopaw/frontend/expert.py` 内或同目录新文件，按现有代码组织就近放置），含建表 / 默认注入 / 查询 + 专家过滤。
- 修改：应用装配处注册路由与初始化 `scenario_registry`。
- 修改：`frontend/src/components/ExpertManagerView.tsx`（新增精选场景区块与数据获取）。
- 新增：对应后端单测与接口测试。

## 10. 假设

- 场景数据本次以内置默认注入为主，无需后台编辑界面。
- 渐变主题键的可选集合与配色由前端集中映射（天蓝系为基调）。
- 复用现有 `auth.db` 与 `check_auth` 鉴权，不引入新存储或鉴权机制。
